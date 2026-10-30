"""`drive_room` 의 매개변수 갈래 검증.

기본값 갈래(대본 13호출, 턴 7 유실)는 `test_generation_replay_reproduces_driver_run.py` 가 바이트 대조로 지킨다. 여기서는
그 테스트가 쓰지 않는 갈래 — 숨김 스탯, 엔딩, 다른 순번의 유실 턴, 상한 면제 — 가 실제 드라이버 산출물에 원하는 흔적을
남기는지만 본다. 대본은 짧게 둔다 — 긴 대본(예: 120턴)도 같은 매개변수로 만들 수 있다."""

import json
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, ChatTurn, User
from driver_harness import (
    DRIVE_EPILOGUE,
    DRIVE_HIDDEN_RULE,
    DRIVE_HIDDEN_STAT_NAME,
    DRIVE_STAT_NAME,
    drive_room,
    says,
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _turn_lines(log: Path) -> list[dict[str, Any]]:
    return [r for r in _jsonl(log) if r["kind"] == "turn"]


def _bytes_of(folder: Path, names: Iterable[str]) -> dict[str, bytes]:
    return {name: (folder / name).read_bytes() for name in names}


async def _chat_turns(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatTurn]:
    return list(
        (
            await db_session.scalars(
                sa.select(ChatTurn).where(ChatTurn.chat_room_id == room_id).order_by(ChatTurn.turn_number)
            )
        ).all()
    )


async def test_hidden_stat_change_is_recorded_in_chat_turns_but_never_reaches_the_driver(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(3),
        failing_generations=(),
        stat_verdicts={2: (DRIVE_HIDDEN_RULE,)},
        hidden_stat=True,
    )
    assert driven.hidden_stat_id is not None

    turns = await _chat_turns(db_session, driven.room_id)
    assert [t.turn_number for t in turns if str(driven.hidden_stat_id) in t.stat_changes] == [2]
    # 드라이버가 본 스탯(방 응답·SSE 누적)에는 보이는 스탯만 있다 — 비어 있어서 숨김 스탯이 없는 것이 아니다. 드라이버는
    # 정의를 모르는 스탯 값을 id 그대로 키로 실으므로, 값만 샌 경우까지 보려고 이름과 id 를 둘 다 본다.
    hidden_keys = {DRIVE_HIDDEN_STAT_NAME, str(driven.hidden_stat_id)}
    seen = [r["roomAfter"]["stats"] for r in _jsonl(driven.log) if r.get("roomAfter")]
    assert seen and all(DRIVE_STAT_NAME in stats and not hidden_keys & stats.keys() for stats in seen), seen


async def test_ending_story_ends_the_driver_with_exit_code_3_on_the_ending_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 종료 코드 3 은 `final_exit` 로 헬퍼가 단언한다 — 첫 호출은 0 이어야 하므로 엔딩이 2턴보다 일찍 오면 헬퍼에서 깨진다.
    driven = await drive_room(
        db_session,
        monkeypatch,
        tmp_path,
        script=says(2),
        failing_generations=(),
        stat_verdicts={},
        ending_turn=2,
        final_exit=3,
    )

    endings = [(r["clientTurn"], r["ending"]) for r in _turn_lines(driven.log)]
    assert [(turn, ending is not None) for turn, ending in endings] == [(1, False), (2, True)]
    assert endings[1][1]["epilogue"] == DRIVE_EPILOGUE


async def test_failing_generation_leaves_two_turn_lines_with_the_same_client_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driven = await drive_room(
        db_session, monkeypatch, tmp_path, script=says(3), failing_generations=(2,), stat_verdicts={}
    )

    lines = _turn_lines(driven.log)
    assert [(r["clientTurn"], r["done"]) for r in lines] == [(1, True), (2, False), (2, True)]
    assert driven.generations == 3


async def test_rate_limit_exempt_user_drives_the_script_with_no_clover_while_a_default_user_pays_each_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 두 런의 작업 폴더를 따로 둔다 — 같은 작업 폴더면 둘째 런이 런 폴더 만들기에서 깨진다.
    exempt_dir, paying_dir = tmp_path / "exempt", tmp_path / "paying"
    exempt_dir.mkdir()
    paying_dir.mkdir()
    exempt = await drive_room(
        db_session,
        monkeypatch,
        exempt_dir,
        script=says(3),
        failing_generations=(),
        stat_verdicts={},
        rate_limit_exempt=True,
    )
    paying = await drive_room(
        db_session, monkeypatch, paying_dir, script=says(3), failing_generations=(), stat_verdicts={}
    )

    # 면제 계정은 잔액 0 으로 대본을 다 돌고, 턴 기록에는 게이트가 깎지 않았다고 남는다.
    exempt_user = await db_session.scalar(sa.select(ChatRoom.user_id).where(ChatRoom.id == exempt.room_id))
    assert await db_session.scalar(sa.select(User.clover_balance).where(User.id == exempt_user)) == 0
    assert [(r["clientTurn"], r["done"]) for r in _turn_lines(exempt.log)] == [(n, True) for n in range(1, 4)]
    assert {t.charge_source for t in await _chat_turns(db_session, exempt.room_id)} == {"skipped"}
    # 면제가 아닌 계정은 장치가 준 클로버로 턴마다 낸다. 주지 않았으면 첫 턴부터 잔액 부족으로 막혀 장치가 깨진다.
    assert [t.charge_source for t in await _chat_turns(db_session, paying.room_id)] == ["clover"] * 3


async def test_export_refuses_a_folder_that_already_holds_a_run_and_leaves_it_untouched(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    export = tmp_path / "export"
    # 두 런의 작업 폴더를 따로 둔다 — 같은 작업 폴더면 둘째 런이 내보내기 전에 런 폴더 만들기에서 먼저 깨져, 거절을 보지 못한다.
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = await drive_room(
        db_session, monkeypatch, first_dir, script=says(1), failing_generations=(), stat_verdicts={}, export_dir=export
    )
    names = [path.name for path in (first.log, first.snapshot_log, first.dump)]
    exported = _bytes_of(export, names)
    assert exported == _bytes_of(first.log.parent, names)

    with pytest.raises(FileExistsError, match="런마다 다른 폴더"):
        await drive_room(
            db_session,
            monkeypatch,
            second_dir,
            script=says(1),
            failing_generations=(),
            stat_verdicts={},
            export_dir=export,
        )
    assert _bytes_of(export, names) == exported
