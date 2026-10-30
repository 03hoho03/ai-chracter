"""측정 드라이버를 테스트 앱에 붙여 방 하나를 도는 장치.

실제 측정 드라이버(`scripts/chat_play.py`)를 이 프로세스의 테스트 앱에 붙여 방 하나를 대본대로 돈다. 드라이버 로그·기억
스냅숏 로그는 드라이버가, 프롬프트 덤프는 앱이 자기 기록 함수로 쓰고, 턴 기록(`chat_turns`)은 테스트 트랜잭션에 남는다.
그 묶음을 읽는 도구의 테스트가 손으로 만든 사본이 아니라 실제 산출물을 읽게 하려는 것이다 — 손으로 만든 사본은 기록
함수가 바뀌어도 그대로라 도구가 사본만 맞추게 된다. 판정·생성·요약 응답은 가짜 LLM 이 낸다(실제 호출 0).

드라이버 모듈을 실제로 import 해 붙이는 장치라 공용 `factories.py` 와 떼어 둔다 — 거기 두면 factories 를 쓰는 모든 테스트가
드라이버 모듈에 묶여, 드라이버 import 가 깨질 때 무관한 테스트까지 함께 깨진다.

아래 기본 작품·대본·판정표와 `drive_room` 안의 접기 설정에서 나오는 값을 `test_generation_replay_reproduces_driver_run.py`
가 기대값으로 고정해 두었다(요약이 실리는 턴, 문턱 위 턴 등). 기본값을 바꾸면 그 테스트의 기대값도 함께 고친다.
"""

import asyncio
import json
import os
import shutil
import uuid
from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import chat_play
from api.chat import memory_fold
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.content.schemas import EndingRuleDraftItem
from api.core import rate_limit_gate
from api.core.config import settings
from api.db.models import KeywordNote, PromptSet, Shortcut, StatDef, StatRule, User
from api.db.models.story import EndingRuleOperator
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.main import app
from api.session.store import create_session
from factories import (
    _add_epilogue_ending,
    _add_situation_note,
    _clear_llm_override,
    _make_default_persona,
    _override_llm_client,
    _story_with_setup,
)

DRIVE_STAT_NAME = "신뢰"
DRIVE_GATE = 70.0
DRIVE_GATED_NOTE = "신뢰가 문턱을 넘은 동안만 실리는 상황"
_DRIVE_ALWAYS_NOTE = "늘 실리는 배경"
_DRIVE_KEYWORD = "등불"
DRIVE_KEYWORD_NOTE = "등불이 나온 뒤 두 턴 실리는 설명"
DRIVE_SHORTCUT_NAME = "수색"
_DRIVE_SHORTCUT_PROMPT = "{{user}}가 주변을 수색하는 장면을 묘사하라"
DRIVE_NOTE_A = "기억 노트 A: 주인공은 겁이 많다"
DRIVE_NOTE_B = "기억 노트 B: 비밀을 들켰다"
_DRIVE_PERSONA_NAME = "하늘"
DRIVE_PERSONA_THEN = "드라이버가 돌 때의 프로필 설명"
# 숨김 스탯을 넣은 작품에서만 쓴다. 판정 프롬프트는 규칙이 있는 스탯에 `order` 순으로 a, b… 글자를 매기므로 신뢰(order 1)
# 다음인 이 스탯(order 2)의 첫 규칙이 b1 이다.
DRIVE_HIDDEN_STAT_NAME = "의심"
DRIVE_HIDDEN_RULE = "b1"
_DRIVE_HIDDEN_DELTA = 20
DRIVE_EPILOGUE = "문이 닫히고 이야기가 끝난다."

# 드라이버 호출 하나 = (방법 `say`·`shortcut`, 발화 또는 단축어 이름, 보내기 전에 설정할 기억 노트).
DriverCall = tuple[str, str, str | None]


def says(count: int) -> list[DriverCall]:
    """발화 `말 1` 부터 `말 {count}` 까지 차례로 보내는 대본(단축어·노트 없음). 길이에 따로 맞출 상한은 없다 — `drive_room` 이
    대본 줄 수만큼 클로버를 준다."""
    return [("say", f"말 {n}", None) for n in range(1, count + 1)]


# 기본 대본. 13번 부르고, 7번째 호출의 생성이 실패해(유실 턴) 다음 호출이 같은 턴을 다시 보낸다 — 성공 턴은 12다.
DRIVE_SCRIPT: list[DriverCall] = [
    ("say", "안녕하세요", None),
    ("say", f"{_DRIVE_KEYWORD}을 들고 간다", DRIVE_NOTE_A),
    ("say", "손을 잡는다", None),
    ("say", "골목으로 들어간다", None),
    ("shortcut", DRIVE_SHORTCUT_NAME, None),
    ("say", "문을 두드린다", None),
    ("say", "대답을 기다린다", DRIVE_NOTE_B),
    ("say", "대답을 다시 기다린다", None),
    ("say", "뒤돌아본다", None),
    ("say", "달린다", None),
    ("say", "숨을 고른다", None),
    ("say", "다시 묻는다", None),
    ("say", "끝낸다", None),
]
# 생성 호출 순번(1부터, 실패한 호출도 센다) 중 실패시킬 것. 실패한 호출의 턴은 서버가 마치지 않으므로, 대본의 다음
# 호출이 같은 턴 번호(`clientTurn`)로 다시 보낸다.
DRIVE_FAILING_GENERATIONS: tuple[int, ...] = (7,)
# 신뢰 규칙 둘(짧은 id 는 판정 프롬프트가 매기는 대로 스탯 글자 + 순번). 초기값 50 에서 올리는 규칙은 문턱 위로, 내리는
# 규칙은 다시 아래로 보낸다.
_DRIVE_RAISE_RULE, _DRIVE_RAISE_DELTA = "a1", 30
_DRIVE_LOWER_RULE, _DRIVE_LOWER_DELTA = "a2", -40
# 생성 호출 순번 → 그 턴 판정이 고르는 규칙들. 3번째(턴 3)에 문턱 위로(80), 10번째(실패한 호출 뒤라 턴 9)에 아래로(40).
DRIVE_STAT_VERDICTS: dict[int, tuple[str, ...]] = {3: (_DRIVE_RAISE_RULE,), 10: (_DRIVE_LOWER_RULE,)}


class ReplayScriptedLLM(LLMClient):
    """드라이버 실행 장치의 가짜 LLM. 생성은 호출 순번이 붙은 짧은 응답(`failing_generations` 의 순번은 실패), 스탯 판정은
    순번별 표(`stat_verdicts`), 요약은 접을 때마다 본문이 다른 글을 낸다 — 요약 본문이 같으면 리플레이가 해시로 스냅숏 행을
    하나로 가려낼 수 없다. 엔딩 판정은 `ending_triggered` 를 줄 때만 받아 그 값으로 답한다. 그 밖의 구조화 호출은
    `AssertionError` 다 — 작품에 없을 판정이 불리면 조용히 넘어가지 않게."""

    def __init__(
        self,
        *,
        failing_generations: Collection[int],
        stat_verdicts: Mapping[int, Sequence[str]],
        ending_triggered: bool | None,
    ) -> None:
        self.generations = 0
        self.summaries = 0
        self._failing_generations = frozenset(failing_generations)
        self._stat_verdicts = stat_verdicts
        self._ending_triggered = ending_triggered

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.generations += 1
        if self.generations in self._failing_generations:
            raise LLMClientError("가짜 생성 실패")
        yield f"응답 {self.generations}. "
        yield "바람이 분다."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=list(self._stat_verdicts.get(self.generations, ())))
        if response_schema is MemorySummaryResult:
            self.summaries += 1
            return MemorySummaryResult(summary=f"[요약 {self.summaries}] 생성 {self.generations}번째까지 접었다")
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        if response_schema is EndingJudgmentResult and self._ending_triggered is not None:
            return EndingJudgmentResult(triggered=self._ending_triggered)
        raise AssertionError(f"예상하지 않은 구조화 호출: {response_schema}")


class AsgiDriverBridge(httpx.BaseTransport):
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
    """드라이버로 돈 방 하나. `log`·`snapshot_log`·`dump` 는 드라이버 로그·기억 스냅숏 로그·프롬프트 덤프이고,
    `generations` 는 가짜 LLM 이 받은 생성 호출 수(실패한 호출 포함)다. `hidden_stat_id` 는 숨김 스탯을 넣은 작품에서만 있다."""

    room_id: uuid.UUID
    setup_id: uuid.UUID
    trust_id: uuid.UUID
    log: Path
    snapshot_log: Path
    dump: Path
    generations: int
    hidden_stat_id: uuid.UUID | None


# 한 런이 남기는 세 파일 — 드라이버 로그, 기억 스냅숏 로그, 프롬프트 덤프.
_RUN_FILES = ("chat.jsonl", "memory-snapshots.jsonl", "prompt-dump.jsonl")


def _refuse_taken_export(export_dir: Path) -> None:
    """내보낼 자리에 같은 이름 파일이 하나라도 있으면 거절한다 — 덮으면 그 폴더에 앞서 내보낸 런의 묶음이 조용히 사라진다."""
    taken = [str(export_dir / name) for name in _RUN_FILES if (export_dir / name).exists()]
    if taken:
        raise FileExistsError(f"내보낼 자리에 이미 파일이 있다 — 런마다 다른 폴더를 준다: {', '.join(taken)}")


def _export_run(run: Path, export_dir: Path) -> None:
    # 시작 전에 비어 있던 자리라도 그사이 다른 런이 같은 폴더로 내보냈을 수 있어 복사 직전에 다시 본다.
    _refuse_taken_export(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    for name in _RUN_FILES:
        shutil.copy2(run / name, export_dir / name)


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


async def _driven_story(
    db_session: AsyncSession, *, hidden_stat: bool, ending_turn: int | None, rate_limit_exempt: bool, paid_turns: int
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None]:
    """스탯 하나(문턱 조건 상황 노트), 상시·키워드 노트, 단축어, 기본 대화 프로필을 갖춘 스토리 작품. 고르면 숨김 스탯(규칙
    하나)과 `ending_turn` 턴에 처음 판정되는 엔딩 하나를 더하고, 사용자를 상한 면제로 둔다. 사용자에게는 기본 모델 턴
    `paid_turns` 번 몫의 클로버를 준다. (사용자 id, 작품 id, 신뢰 스탯 entity_id, 시작 설정 행 id, 숨김 스탯 entity_id)를
    돌려준다."""
    user_id, content, setup = await _story_with_setup(
        db_session, opening_message="{{user}}, 문이 열린다.", paid_turns=paid_turns
    )
    trust, trust_row = uuid.uuid4(), uuid.uuid4()
    db_session.add(
        StatDef(
            id=trust_row,
            entity_id=trust,
            starting_setup_id=setup.id,
            name=DRIVE_STAT_NAME,
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
            StatRule(
                entity_id=uuid.uuid4(),
                stat_def_id=trust_row,
                condition="믿음을 얻는다",
                delta=_DRIVE_RAISE_DELTA,
                order=0,
            ),
            StatRule(
                entity_id=uuid.uuid4(),
                stat_def_id=trust_row,
                condition="믿음을 잃는다",
                delta=_DRIVE_LOWER_DELTA,
                order=1,
            ),
        ]
    )
    hidden: uuid.UUID | None = None
    if hidden_stat:
        hidden, hidden_row = uuid.uuid4(), uuid.uuid4()
        db_session.add(
            StatDef(
                id=hidden_row,
                entity_id=hidden,
                starting_setup_id=setup.id,
                name=DRIVE_HIDDEN_STAT_NAME,
                icon="heart",
                color="#000000",
                min_value=0,
                max_value=100,
                initial_value=50,
                unit=None,
                description="의심",
                order=2,
                hidden_from_player=True,
            )
        )
        db_session.add(
            StatRule(
                entity_id=uuid.uuid4(),
                stat_def_id=hidden_row,
                condition="의심을 산다",
                delta=_DRIVE_HIDDEN_DELTA,
                order=0,
            )
        )
    rule = EndingRuleDraftItem(
        id=uuid.uuid4(), stat_id=trust, operator=EndingRuleOperator("gte"), threshold=DRIVE_GATE, next_op=None
    )
    _add_situation_note(db_session, setup, DRIVE_GATED_NOTE, [rule])
    version_id = content.current_published_version_id
    assert version_id is not None
    db_session.add_all(
        [
            KeywordNote(
                entity_id=uuid.uuid4(),
                content_version_id=version_id,
                starting_setup_id=None,
                info_text=_DRIVE_ALWAYS_NOTE,
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
                info_text=DRIVE_KEYWORD_NOTE,
                trigger_keywords=[_DRIVE_KEYWORD],
                order=1,
                exclude_keywords=[],
                sticky_turns=2,
                always_on=False,
            ),
            Shortcut(
                entity_id=uuid.uuid4(),
                content_version_id=version_id,
                name=DRIVE_SHORTCUT_NAME,
                description="주변 살피기",
                prompt=_DRIVE_SHORTCUT_PROMPT,
            ),
        ]
    )
    if ending_turn is not None:
        # 엔딩 판정은 게이트 턴부터 5턴마다 돈다 — 게이트를 이 턴으로 두면 처음 판정되는 턴이 이 턴이다.
        ending = await _add_epilogue_ending(db_session, setup, DRIVE_EPILOGUE)
        ending.turn_count_gate = ending_turn
    persona = await _make_default_persona(db_session, user_id, _DRIVE_PERSONA_NAME)
    persona.description = DRIVE_PERSONA_THEN
    if rate_limit_exempt:
        user = await db_session.get(User, user_id)
        assert user is not None
        user.rate_limit_exempt = True
    await db_session.commit()
    return user_id, content.id, trust, setup.id, hidden


async def drive_room(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    work_dir: Path,
    *,
    script: Sequence[DriverCall] = DRIVE_SCRIPT,
    failing_generations: Collection[int] = DRIVE_FAILING_GENERATIONS,
    stat_verdicts: Mapping[int, Sequence[str]] = DRIVE_STAT_VERDICTS,
    hidden_stat: bool = False,
    ending_turn: int | None = None,
    rate_limit_exempt: bool = False,
    final_exit: int = 0,
    export_dir: Path | None = None,
) -> DrivenRoom:
    """작품을 만들고 드라이버로 방을 만든 뒤 `script` 를 차례로 보낸다. 부르는 테스트는 `db_client` 픽스처도 받아야 한다 —
    그 픽스처가 앱의 DB 세션을 이 테스트 트랜잭션에 묶어, 드라이버가 만든 방을 `db_session` 이 본다.

    - `failing_generations`·`stat_verdicts`: 가짜 LLM 의 생성 실패 순번과 순번별 발동 규칙(`ReplayScriptedLLM`). 실패한 호출
      다음 대본 줄이 같은 턴을 다시 보내므로, 실패 하나마다 대본에 호출이 하나 더 있어야 그 턴이 끝난다.
    - `hidden_stat`: 플레이어에게 숨긴 스탯(`DRIVE_HIDDEN_STAT_NAME`, 규칙 `DRIVE_HIDDEN_RULE`)을 더한다.
    - `ending_turn`: 그 턴에 처음 판정되고 발동하는 엔딩을 더한다. 드라이버는 엔딩에 닿은 호출에서 종료 코드 3 을 내고 방은
      더 받지 않으므로, 대본은 그 턴에서 끝내고 `final_exit=3` 을 준다.
    - `rate_limit_exempt`: 사용자를 상한 면제 계정으로 둔다. 면제 계정의 기본 모델 턴은 게이트가 깎지 않아 턴 기록의 차감
      출처가 `skipped` 이고, 장치도 이 계정에는 클로버를 주지 않는다. 면제가 아니면 대본 한 줄마다 기본 모델 턴 한 번 몫을
      줘 턴마다 클로버로 낸다(차감 출처 `clover`). 분당 상한은 면제 계정에도 걸려 여기서 늘 풀어 둔다.
    - `final_exit`: 대본 마지막 호출의 드라이버 종료 코드. 그 앞 호출과 방 만들기는 늘 0 이어야 한다.
    - `export_dir`: 주면 다 돈 뒤 세 파일을 그 폴더로 복사한다(드라이버는 로그에 덧붙여 쓰므로 그 폴더에 바로 쓰지 않는다).
      런마다 다른 폴더를 준다 — 같은 이름 파일이 이미 있으면 덮지 않고 `FileExistsError` 로 거절한다(작품을 만들기 전에 한
      번, 복사 직전에 한 번 본다).
    """
    if export_dir is not None:
        # 긴 대본을 다 돈 뒤에야 거절되지 않게 시작 전에 먼저 본다.
        _refuse_taken_export(export_dir)
    # 대본 한 줄이 게이트를 지나 한 턴 몫을 깎는 호출 하나다. 생성이 실패한 줄은 깎인 뒤 그 응답 안에서 되돌려 받지만,
    # 그 환급에 기대지 않게 줄마다 한 턴 몫을 준다. 면제 계정의 기본 모델 턴은 게이트가 깎지 않으므로 주지 않는다 — 잔액
    # 없이 대본을 다 도는 것이 면제가 걸렸다는 증거가 된다.
    user_id, content_id, trust, setup_id, hidden = await _driven_story(
        db_session,
        hidden_stat=hidden_stat,
        ending_turn=ending_turn,
        rate_limit_exempt=rate_limit_exempt,
        paid_turns=0 if rate_limit_exempt else len(script),
    )
    # 마이그레이션은 새 시드 세트를 `max(지금, 원본 + 1초)` 에 게시해, 세트가 여럿 쌓인 레인의 활성 세트는 몇 초 뒤
    # 시각으로 찍힌다. 그 시각보다 먼저 보낸 턴에서 서버는 그 세트를 쓰지만 리플레이는 "턴보다 먼저 게시된 세트"를 골라
    # 어긋난다(테스트 DB 에서만 생기는 일). 순서는 그대로 두고 모두 과거로 옮긴다.
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    cookie, cred = work_dir / "cookie", work_dir / "cred.json"
    # 로그인 요청을 건너뛴다 — 드라이버는 쿠키 파일이 있으면 그 값을 그대로 쓴다.
    _write_private(cookie, await create_session(user_id))
    _write_private(cred, json.dumps({"email": "unused@example.com", "password": "unused"}))
    run = work_dir / "run"
    run.mkdir()
    log, snapshot_log, dump = (run / name for name in _RUN_FILES)

    monkeypatch.setattr(chat_play, "MIN_GAP", 0.0)
    # 분당 턴 상한(10)은 상한 면제 계정에도 걸린다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 1000)
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    # 4턴째부터 2턴마다 접는다 — 기본 대본의 12턴에 다섯 번.
    monkeypatch.setattr(memory_fold, "FOLD_AT_TURNS", 4)
    monkeypatch.setattr(memory_fold, "FOLD_TURNS", 2)
    llm = ReplayScriptedLLM(
        failing_generations=failing_generations,
        stat_verdicts=stat_verdicts,
        ending_triggered=True if ending_turn is not None else None,
    )
    _override_llm_client(llm)
    loop = asyncio.get_running_loop()
    bridge = AsgiDriverBridge(loop)

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
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        room_id = next(r["roomId"] for r in records if r["kind"] == "opening")
        for index, (how, text, note) in enumerate(script, start=1):
            argv = ["--room", room_id]
            if note is not None:
                note_file = work_dir / "note.txt"
                note_file.write_text(note, encoding="utf-8")
                argv += ["--set-note", str(note_file)]
            argv += ["--shortcut", text] if how == "shortcut" else ["--say", text]
            assert await drive(argv) == (final_exit if index == len(script) else 0), (how, text)
    finally:
        _clear_llm_override()
        monkeypatch.setattr(settings, "prompt_dump_path", None)

    if export_dir is not None:
        _export_run(run, export_dir)
    return DrivenRoom(
        room_id=uuid.UUID(room_id),
        setup_id=setup_id,
        trust_id=trust,
        log=log,
        snapshot_log=snapshot_log,
        dump=dump,
        generations=llm.generations,
        hidden_stat_id=hidden,
    )
