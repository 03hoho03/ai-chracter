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

import json
import os
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import generation_replay
from api.chat.memory_window import load_current_summary
from api.chat.room_stats import load_room_stats
from api.db.models import ChatRoom, ChatRoomMemorySnapshot
from api.db.models.persona import UserPersona
from driver_harness import (
    DRIVE_GATE as GATE,
    DRIVE_GATED_NOTE as GATED_NOTE,
    DRIVE_KEYWORD_NOTE as KEYWORD_NOTE,
    DRIVE_NOTE_A as NOTE_A,
    DRIVE_NOTE_B as NOTE_B,
    DRIVE_PERSONA_THEN as PERSONA_THEN,
    DRIVE_SCRIPT as SCRIPT,
    DRIVE_SHORTCUT_NAME as SHORTCUT_NAME,
    DRIVE_STAT_NAME as STAT_NAME,
    DrivenRoom,
    drive_room,
)
from factories import _FakeProviderSdks
from replay.assemble import TurnAssembly, assemble_turn
from replay.logs import load_driver_logs

PERSONA_NOW = "드라이버를 돌린 뒤 고친 프로필 설명"
TURNS = list(range(1, 13))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
async def driven(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> DrivenRoom:
    """작품을 만들고 드라이버로 방을 만든 뒤 대본을 돈다. 끝나면 대화 프로필 설명을 바꾼다."""
    driven_room = await drive_room(db_session, monkeypatch, tmp_path)
    room = await db_session.get(ChatRoom, driven_room.room_id)
    assert room is not None and room.persona_id is not None
    await db_session.execute(
        sa.update(UserPersona).where(UserPersona.id == room.persona_id).values(description=PERSONA_NOW)
    )
    await db_session.commit()
    return driven_room


def _generation_dump(driven: DrivenRoom) -> list[dict[str, Any]]:
    """덤프의 생성 줄. 같은 덤프에 판정 프롬프트 줄(`kind` 가 `judgment`)도 남는다."""
    return [r for r in _jsonl(driven.dump) if r["kind"] == "generation"]


def _dumped_prompts(driven: DrivenRoom) -> dict[int, str]:
    """턴 → 서버가 그 턴에 마지막으로 덤프한 생성 프롬프트(유실 턴의 재시도가 앞 시도를 덮는다)."""
    return {r["turn"]: r["prompt"] for r in _generation_dump(driven) if r["roomId"] == str(driven.room_id)}


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
    assert [r["turn"] for r in _generation_dump(driven)] == [1, 2, 3, 4, 5, 6, 7, 7, 8, 9, 10, 11, 12]
    # 성공한 턴마다 스탯 판정 줄이 생성 줄 뒤에 남았다 — 리플레이는 이 줄들을 거르고도 아래 기준을 채워야 한다.
    judged = [(r["turn"], r["callSite"]) for r in _jsonl(driven.dump) if r["kind"] == "judgment"]
    assert [turn for turn, call_site in judged if call_site == "chat_stat_judgment"] == list(range(1, 13))
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
