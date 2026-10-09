"""측정 드라이버를 테스트 앱에 실제로 붙여 스토리 방을 여러 턴 돈 뒤, 생성 리플레이가 그 방의 모든 턴을 서버가 그때
덤프한 프롬프트와 바이트까지 같게 다시 조립하는지 본다. 판정·생성·요약 응답은 가짜 LLM 이 낸다(실제 호출 0).

로그는 드라이버가 자기 기록 함수로 쓰고, 덤프는 앱이 턴마다 쓴다 — 이 파일은 둘 다 손으로 만들지 않는다. 리플레이가
손으로 만든 사본만 맞추는 일을 막기 위해서다. 대본은 리플레이가 지난 턴의 값 대신 DB 의 지금 값을 읽으면 어긋나도록
짰다: 기억 노트를 두 번 바꾸고, 스탯이 상황 노트의 문턱을 올라갔다 내려오고, 요약이 여러 번 접히고, 단축어 턴과 생성
실패 뒤 재시도 턴이 있다. 드라이버를 돌린 뒤에는 대화 프로필 설명도 바꾼다. 이 조건이 실제로 성립하는지도 함께 본다 —
성립하지 않으면 바이트 일치는 아무것도 보증하지 못한다.

`REPLAY_REPRO_EXPORT_DIR` 환경 변수를 주면 둘째 테스트가 드라이버 로그·기억 스냅숏 로그·프롬프트 덤프와 리플레이의
갈래별 호출 기록을 그 폴더로 복사한다. 대화 품질 쌍 판정 도구가 이 기록을 쌍으로 읽는지 비용 없이 확인하는 재료다.
주지 않으면 테스트 임시 폴더에만 남는다.
"""

import asyncio
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import chat_play
import generation_replay
from api.chat import memory_fold
from api.chat.prompt_builder import (
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.chat.memory_window import load_current_summary
from api.chat.room_stats import load_room_stats
from api.content.schemas import EndingRuleDraftItem
from api.core import rate_limit_gate
from api.core.config import settings
from api.db.models import ChatRoom, ChatRoomMemorySnapshot, KeywordNote, Shortcut, StatDef, StatRule
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSet
from api.db.models.story import EndingRuleOperator
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.main import app
from api.session.store import create_session
from factories import (
    _add_situation_note,
    _clear_llm_override,
    _FakeProviderSdks,
    _make_default_persona,
    _override_llm_client,
    _story_with_setup,
)
from replay.assemble import TurnAssembly, assemble_turn
from replay.logs import load_driver_logs

STAT_NAME = "신뢰"
GATE = 70.0
GATED_NOTE = "신뢰가 문턱을 넘은 동안만 실리는 상황"
ALWAYS_NOTE = "늘 실리는 배경"
KEYWORD = "등불"
KEYWORD_NOTE = "등불이 나온 뒤 두 턴 실리는 설명"
SHORTCUT_NAME = "수색"
SHORTCUT_PROMPT = "{{user}}가 주변을 수색하는 장면을 묘사하라"
NOTE_A = "기억 노트 A: 주인공은 겁이 많다"
NOTE_B = "기억 노트 B: 비밀을 들켰다"
PERSONA_NAME = "하늘"
PERSONA_THEN = "드라이버가 돌 때의 프로필 설명"
PERSONA_NOW = "드라이버를 돌린 뒤 고친 프로필 설명"
# 드라이버 호출 하나 = (방법, 발화 또는 단축어 이름, 보내기 전에 설정할 기억 노트). 13번 부르고, 7번째 호출의 생성이
# 실패해(유실 턴) 다음 호출이 같은 턴을 다시 보낸다 — 성공 턴은 12다.
SCRIPT: list[tuple[str, str, str | None]] = [
    ("say", "안녕하세요", None),
    ("say", f"{KEYWORD}을 들고 간다", NOTE_A),
    ("say", "손을 잡는다", None),
    ("say", "골목으로 들어간다", None),
    ("shortcut", SHORTCUT_NAME, None),
    ("say", "문을 두드린다", None),
    ("say", "대답을 기다린다", NOTE_B),
    ("say", "대답을 다시 기다린다", None),
    ("say", "뒤돌아본다", None),
    ("say", "달린다", None),
    ("say", "숨을 고른다", None),
    ("say", "다시 묻는다", None),
    ("say", "끝낸다", None),
]
TURNS = list(range(1, 13))
FAILING_GENERATION = 7
# 신뢰 규칙 둘(짧은 id 는 판정 프롬프트가 매기는 대로 스탯 글자 + 순번). 초기값 50 에서 올리는 규칙은 문턱 위로, 내리는
# 규칙은 다시 아래로 보낸다.
RAISE_RULE, RAISE_DELTA = "a1", 30
LOWER_RULE, LOWER_DELTA = "a2", -40
# 생성 호출 순번 → 그 턴 판정이 고르는 규칙. 3번째(턴 3)에 문턱 위로(80), 10번째(실패한 호출 뒤라 턴 9)에 아래로(40).
STAT_VERDICTS = {3: RAISE_RULE, 10: LOWER_RULE}


class _ScriptedLLM(LLMClient):
    """생성은 호출 순번이 붙은 짧은 응답(정해진 순번은 실패), 판정은 순번별 표, 요약은 접을 때마다 본문이 다른 글을 낸다
    — 요약 본문이 같으면 리플레이가 해시로 스냅숏 행을 하나로 가려낼 수 없다."""

    def __init__(self) -> None:
        self.generations = 0
        self.summaries = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generations += 1
        if self.generations == FAILING_GENERATION:
            raise LLMClientError("가짜 생성 실패")
        yield f"응답 {self.generations}. "
        yield "바람이 분다."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            fired = STAT_VERDICTS.get(self.generations)
            return StatRuleJudgmentResult(fired_rule_ids=[] if fired is None else [fired])
        if response_schema is MemorySummaryResult:
            self.summaries += 1
            return MemorySummaryResult(summary=f"[요약 {self.summaries}] 생성 {self.generations}번째까지 접었다")
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        raise AssertionError(f"예상하지 않은 구조화 호출: {response_schema}")


class _AsgiBridge(httpx.BaseTransport):
    """드라이버의 동기 요청을 테스트 이벤트 루프의 앱으로 넘긴다. 드라이버는 다른 스레드에서 돈다. 앱은 응답 뒤
    백그라운드 작업(요약 접기)까지 마친 뒤 응답을 돌려주므로, 다음 턴은 접기가 끝난 방에서 시작한다."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._inner = httpx.ASGITransport(app=app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()

        async def call() -> tuple[int, httpx.Headers, bytes]:
            forwarded = httpx.Request(request.method, request.url, headers=request.headers, content=body)
            response = await self._inner.handle_async_request(forwarded)
            raw = b"".join([chunk async for chunk in response.aiter_raw()])
            await response.aclose()
            return response.status_code, response.headers, raw

        status, headers, raw = asyncio.run_coroutine_threadsafe(call(), self._loop).result(timeout=60)
        return httpx.Response(status, headers=headers, content=raw, request=request)


@dataclass
class DrivenRoom:
    room_id: uuid.UUID
    setup_id: uuid.UUID
    trust_id: uuid.UUID
    log: Path
    snapshot_log: Path
    dump: Path
    generations: int


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


async def _story(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """스탯 하나(문턱 조건 상황 노트), 상시·키워드 노트, 단축어, 기본 대화 프로필을 갖춘 스토리 작품. (사용자 id, 작품
    id, 스탯 entity_id, 시작 설정 행 id)를 돌려준다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="{{user}}, 문이 열린다.")
    trust, trust_row = uuid.uuid4(), uuid.uuid4()
    db_session.add(
        StatDef(
            id=trust_row,
            entity_id=trust,
            starting_setup_id=setup.id,
            name=STAT_NAME,
            icon="heart",
            color="#ff0000",
            min_value=0,
            max_value=100,
            initial_value=50,
            unit=None,
            description="신뢰",
            order=1,
        )
    )
    db_session.add_all(
        [
            StatRule(entity_id=uuid.uuid4(), stat_def_id=trust_row, condition="믿음을 얻는다", delta=RAISE_DELTA, order=0),
            StatRule(entity_id=uuid.uuid4(), stat_def_id=trust_row, condition="믿음을 잃는다", delta=LOWER_DELTA, order=1),
        ]
    )
    rule = EndingRuleDraftItem(
        id=uuid.uuid4(), stat_id=trust, operator=EndingRuleOperator("gte"), threshold=GATE, next_op=None
    )
    _add_situation_note(db_session, setup, GATED_NOTE, [rule])
    version_id = content.current_published_version_id
    assert version_id is not None
    db_session.add_all(
        [
            KeywordNote(
                entity_id=uuid.uuid4(),
                content_version_id=version_id,
                starting_setup_id=None,
                info_text=ALWAYS_NOTE,
                trigger_keywords=[],
                order=0,
                exclude_keywords=[],
                sticky_turns=0,
                always_on=True,
            ),
            KeywordNote(
                entity_id=uuid.uuid4(),
                content_version_id=version_id,
                starting_setup_id=None,
                info_text=KEYWORD_NOTE,
                trigger_keywords=[KEYWORD],
                order=1,
                exclude_keywords=[],
                sticky_turns=2,
                always_on=False,
            ),
            Shortcut(
                entity_id=uuid.uuid4(),
                content_version_id=version_id,
                name=SHORTCUT_NAME,
                description="주변 살피기",
                prompt=SHORTCUT_PROMPT,
            ),
        ]
    )
    persona = await _make_default_persona(db_session, user_id, PERSONA_NAME)
    persona.description = PERSONA_THEN
    await db_session.commit()
    return user_id, content.id, trust, setup.id


@pytest.fixture
async def driven(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> DrivenRoom:
    """작품을 만들고 드라이버로 방을 만든 뒤 대본을 돈다. 끝나면 대화 프로필 설명을 바꾼다."""
    user_id, content_id, trust, setup_id = await _story(db_session)
    # 마이그레이션은 새 시드 세트를 `max(지금, 원본 + 1초)` 에 게시해, 세트가 여럿 쌓인 레인의 활성 세트는 몇 초 뒤
    # 시각으로 찍힌다. 그 시각보다 먼저 보낸 턴에서 서버는 그 세트를 쓰지만 리플레이는 "턴보다 먼저 게시된 세트"를 골라
    # 어긋난다(테스트 DB 에서만 생기는 일). 순서는 그대로 두고 모두 과거로 옮긴다.
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    cookie, cred = tmp_path / "cookie", tmp_path / "cred.json"
    # 로그인 요청을 건너뛴다 — 드라이버는 쿠키 파일이 있으면 그 값을 그대로 쓴다.
    _private(cookie, await create_session(user_id))
    _private(cred, json.dumps({"email": "unused@example.com", "password": "unused"}))
    run = tmp_path / "run"
    run.mkdir()
    log, snapshot_log, dump = run / "chat.jsonl", run / "memory-snapshots.jsonl", run / "prompt-dump.jsonl"

    monkeypatch.setattr(chat_play, "MIN_GAP", 0.0)
    # 분당 턴 상한(10)은 상한 면제 계정에도 걸린다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 1000)
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    # 4턴째부터 2턴마다 접는다 — 12턴에 다섯 번.
    monkeypatch.setattr(memory_fold, "FOLD_AT_TURNS", 4)
    monkeypatch.setattr(memory_fold, "FOLD_TURNS", 2)
    llm = _ScriptedLLM()
    _override_llm_client(llm)
    loop = asyncio.get_running_loop()
    bridge = _AsgiBridge(loop)

    def read_db_room(room_id: str) -> chat_play.DbRoom | None:
        # 드라이버의 방 고정값 읽기도 테스트 트랜잭션을 봐야 한다(다른 연결은 이 방을 보지 못한다).
        future = asyncio.run_coroutine_threadsafe(chat_play.read_db_room(db_session, uuid.UUID(room_id)), loop)
        return future.result(timeout=30)

    common = [
        "--base",
        "http://testserver",
        "--cred-file",
        str(cred),
        "--cookie-file",
        str(cookie),
        "--log",
        str(log),
        "--snapshot-log",
        str(snapshot_log),
    ]

    async def drive(argv: list[str]) -> int:
        return await asyncio.to_thread(chat_play.main, [*common, *argv], bridge, read_db_room)

    try:
        assert await drive(["--content-id", str(content_id)]) == 0
        room_id = next(r["roomId"] for r in _jsonl(log) if r["kind"] == "opening")
        for how, text, note in SCRIPT:
            argv = ["--room", room_id]
            if note is not None:
                note_file = tmp_path / "note.txt"
                note_file.write_text(note, encoding="utf-8")
                argv += ["--set-note", str(note_file)]
            argv += ["--shortcut", text] if how == "shortcut" else ["--say", text]
            assert await drive(argv) == 0, (how, text)
    finally:
        _clear_llm_override()
        monkeypatch.setattr(settings, "prompt_dump_path", None)

    room = await db_session.get(ChatRoom, uuid.UUID(room_id))
    assert room is not None and room.persona_id is not None
    await db_session.execute(
        sa.update(UserPersona).where(UserPersona.id == room.persona_id).values(description=PERSONA_NOW)
    )
    await db_session.commit()
    return DrivenRoom(
        room_id=uuid.UUID(room_id),
        setup_id=setup_id,
        trust_id=trust,
        log=log,
        snapshot_log=snapshot_log,
        dump=dump,
        generations=llm.generations,
    )


def _dumped_prompts(driven: DrivenRoom) -> dict[int, str]:
    """턴 → 서버가 그 턴에 마지막으로 덤프한 프롬프트(유실 턴의 재시도가 앞 시도를 덮는다)."""
    return {r["turn"]: r["prompt"] for r in _jsonl(driven.dump) if r["roomId"] == str(driven.room_id)}


def _note_sent_at(driven: DrivenRoom, turn: int) -> str:
    """드라이버가 턴을 보내기 직전에 남긴 기억 스냅숏 중 그 턴 이하의 마지막 것의 노트."""
    snapshots = [r for r in _jsonl(driven.snapshot_log) if r["kind"] == "memorySnapshot" and r["turn"] <= turn]
    return str(snapshots[-1]["note"])


def _summary_sent_at(driven: DrivenRoom, turn: int) -> str:
    snapshots = [r for r in _jsonl(driven.snapshot_log) if r["kind"] == "memorySnapshot" and r["turn"] <= turn]
    return str(snapshots[-1]["summary"])


async def test_replay_reassembles_every_turn_of_a_real_driver_run_byte_identical_to_the_server_dump(
    db_session: AsyncSession, driven: DrivenRoom
) -> None:
    lines = _jsonl(driven.log)
    turn_lines = [r for r in lines if r["kind"] == "turn"]
    dumped = _dumped_prompts(driven)
    # 대본이 그대로 돌았다: 13번 생성을 불렀고 한 번 실패해 그 턴이 덤프에 두 번 남았다.
    assert driven.generations == len(SCRIPT)
    assert [r["turn"] for r in _jsonl(driven.dump)] == [1, 2, 3, 4, 5, 6, 7, 7, 8, 9, 10, 11, 12]
    assert [r["done"] for r in turn_lines].count(False) == 1

    logs = load_driver_logs(driven.log, driven.snapshot_log, driven.room_id)
    assemblies: dict[int, TurnAssembly] = {}
    for turn in TURNS:
        assemblies[turn] = await assemble_turn(
            db_session, room_id=driven.room_id, turn=turn, logs=logs, dump=driven.dump
        )

    # 통과 기준 1 — 성공한 모든 턴이 프롬프트·지시문 둘 다 바이트 일치.
    mismatched = [turn for turn, a in assemblies.items() if not a.window_identical]
    assert mismatched == [], {t: assemblies[t].checks["firstDifferenceAt"] for t in mismatched}

    # 통과 기준 2 — 요약이 실린 턴은 모두 본문 해시로 찾은 스냅숏 커서를 썼고, 그중 하나 이상은 가장 최근 스냅숏이 아니다.
    final_summary = await load_current_summary(db_session, driven.room_id)
    assert final_summary is not None
    folds = await db_session.scalar(
        sa.select(sa.func.count()).where(ChatRoomMemorySnapshot.chat_room_id == driven.room_id)
    )
    assert folds is not None and folds >= 2
    summarised = [turn for turn in TURNS if "[요약 " in dumped[turn]]
    # 덤프에서 읽은 목록만 보면 서버와 리플레이가 함께 요약을 빠뜨려도 통과한다 — 이 대본에서 요약이 실리는 턴을 고정해
    # 둔다. 대본의 턴 수·접기 설정(`FOLD_AT_TURNS`·`FOLD_TURNS`)·실패하는 생성 호출을 바꾸면 이 목록도 같이 고친다.
    assert summarised == list(range(5, 13)), summarised
    for turn in TURNS:
        cursor = assemblies[turn].state["summaryCursor"]
        if turn in summarised:
            assert cursor is not None and cursor["rule"] == "sha256", (turn, cursor)
        else:
            assert cursor is None, (turn, cursor)
    older_cursor = [
        turn
        for turn in summarised
        if assemblies[turn].state["summaryCursor"]["messageId"] != str(final_summary.cursor[1])
    ]
    assert older_cursor, "모든 턴이 가장 최근 스냅숏을 썼다 — 해시로 찾기와 최신 스냅숏 쓰기를 가르지 못한다"

    # 통과 기준 3 — 유실 턴과 그 재시도까지 드라이버 턴 번호가 서버 턴 수 + 1 이다.
    assert [(r["clientTurn"], r["turnBefore"] + 1) for r in turn_lines if r["clientTurn"] != r["turnBefore"] + 1] == []

    # 신호 — 노트: 어떤 턴에 보낸 노트가 지금 DB 노트와 다르고, 그 턴의 덤프에는 지금 노트가 없다.
    room = await db_session.get(ChatRoom, driven.room_id)
    assert room is not None and room.memory_note == NOTE_B
    note_differs = [turn for turn in TURNS if _note_sent_at(driven, turn) != room.memory_note]
    assert note_differs and all(NOTE_B not in dumped[turn] for turn in note_differs), note_differs
    assert NOTE_A in dumped[note_differs[-1]]

    # 신호 — 스탯: 주입한 값이 지금 DB 값과 다른 턴이 있고, 문턱 위·아래 턴이 모두 대상이며, 덤프에 상황 노트가 실린
    # 턴이 정확히 문턱 위인 턴이다.
    _, _, final_stats = await load_room_stats(db_session, driven.room_id, driven.setup_id)
    final_trust = final_stats[str(driven.trust_id)]
    injected = {turn: assemblies[turn].stats_before[STAT_NAME] for turn in TURNS}
    above = [turn for turn in TURNS if injected[turn] >= GATE]
    below = [turn for turn in TURNS if injected[turn] < GATE]
    assert above and below and final_trust < GATE
    assert [turn for turn in TURNS if injected[turn] != final_trust]
    assert [turn for turn in TURNS if GATED_NOTE in dumped[turn]] == above

    # 신호 — 요약: 어떤 턴에 보낸 요약 본문이 지금(가장 최근) 요약과 다르다.
    assert [turn for turn in TURNS if _summary_sent_at(driven, turn) != final_summary.text]

    # 신호 — 단축어: 단축어 턴이 대상에 있다.
    shortcut_turns = [r["clientTurn"] for r in turn_lines if r["shortcut"] == SHORTCUT_NAME and r["done"]]
    assert len(shortcut_turns) == 1 and shortcut_turns[0] in TURNS

    # 신호 — 대화 프로필: 덤프에는 그때 설명이 실렸고 DB 는 지금 고쳐진 설명이다. 그래도 기준 1 이 성립했다.
    assert all(PERSONA_THEN in dumped[turn] and PERSONA_NOW not in dumped[turn] for turn in TURNS)
    persona = await db_session.get(UserPersona, room.persona_id)
    assert persona is not None and persona.description == PERSONA_NOW
    assert {a.state["persona"] for a in assemblies.values()} == {"roomStatic"}

    # 대본의 키워드가 실제로 걸렸다(키워드 턴부터 실리고 그 앞에는 없다).
    assert KEYWORD_NOTE not in dumped[1] and KEYWORD_NOTE in dumped[2]


async def test_replay_execute_writes_window_and_model_arm_records_for_the_driver_run(
    db_session: AsyncSession, driven: DrivenRoom, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sdks = _FakeProviderSdks(monkeypatch)
    out = tmp_path / "replay" / "gen"
    argv = ["--room", str(driven.room_id)]
    for turn in TURNS:
        argv += ["--turn", str(turn)]
    argv += [
        "--dump",
        str(driven.dump),
        "--log",
        str(driven.log),
        "--snapshot-log",
        str(driven.snapshot_log),
        "--model",
        "sonnet",
        "--arm",
        "sonnet",
        "--reps",
        "2",
        "--limit-calls",
        str(len(TURNS) * 2 * 2),
        "--out",
        str(out),
        "--execute",
    ]
    args, arm = generation_replay.parse_args(argv)
    assert await generation_replay.run(args, arm, db_session, client_factory=sdks.client) == 0

    window_file, arm_file = Path(f"{out}.window.jsonl"), Path(f"{out}.sonnet.jsonl")
    for path, variant in ((window_file, "window"), (arm_file, "model")):
        records = _jsonl(path)
        assert all(r["passed"] for r in records if r["kind"] == "plan")
        calls = [(r["turn"], r["rep"], r["variant"], r["error"]) for r in records if r["kind"] == "call"]
        assert calls == [(turn, rep, variant, None) for turn in TURNS for rep in (0, 1)]
    assert sdks.built == 1
    assert (len(sdks.gemini_sent), len(sdks.bedrock_sent)) == (len(TURNS) * 2, len(TURNS) * 2)

    export = os.environ.get("REPLAY_REPRO_EXPORT_DIR")
    if export:
        target = Path(export)
        (target / "replay").mkdir(parents=True, exist_ok=True)
        for path in (driven.log, driven.snapshot_log, driven.dump):
            shutil.copy2(path, target / path.name)
        for path in (window_file, arm_file):
            shutil.copy2(path, target / "replay" / path.name)
