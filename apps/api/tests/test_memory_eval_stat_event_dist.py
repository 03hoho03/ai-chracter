"""판정 이벤트 로그(`chat_turns.stat_events`) 분포 집계 — 합성 행으로 원소 종류·발동 수·잘림·적용 규칙·행마다의 일치 불변식을
센다. 실제 `chat_turns` 대신 같은 이름의 임시 테이블을 세션에 만들어(임시 스키마가 먼저 찾아진다) 집계 SQL 을 그대로 돌린다."""

import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from memory_eval.stat_event_dist import (
    LIVE_FILTER,
    read_only_connection,
    stat_event_distribution,
    stat_events_sql,
    stat_repeat_distribution,
    stat_repeat_sql,
    summarize_repeat_rows,
)

SINCE = datetime(2026, 1, 2, tzinfo=UTC)
INSIDE = datetime(2026, 1, 3, tzinfo=UTC)
BEFORE = datetime(2026, 1, 1, tzinfo=UTC)


def _ref(name: str) -> dict[str, str]:
    return {"entityId": f"{name}-entity", "id": f"{name}-row"}


def _judged(stat: str, fired: list[str], applied: str, delta: float, clamped: bool) -> dict[str, Any]:
    return {
        "statEntityId": stat,
        "firedRuleIds": [_ref(name) for name in fired],
        "appliedRuleId": _ref(applied),
        "delta": delta,
        "clamped": clamped,
    }


def _counter(stat: str, delta: float, clamped: bool) -> dict[str, Any]:
    return {"statEntityId": stat, "counter": True, "delta": delta, "clamped": clamped}


# (kind, stat_events, stat_changes, created_at). 기대값은 아래 테스트가 행마다 손으로 센다.
ROWS: list[tuple[str, list[Any], dict[str, Any], datetime]] = [
    # R1 보내기 — 두 규칙 발동, 폭 큰 쪽 적용, 잘림 없음, 키와 폭 일치.
    ("send", [_judged("a", ["r1", "r2"], "r2", 5, False)], {"a": [10, 15]}, INSIDE),
    # R2 보내기 — 카운터 하나 + 최대에서 잘린 판정 스탯(같은 방향, 폭보다 작게 움직임).
    ("send", [_counter("c", -1, False), _judged("a", ["r1"], "r1", 3, True)], {"c": [5, 4], "a": [98, 100]}, INSIDE),
    # R3 수정 — 이미 최소라 잘린 카운터, 값 그대로라 키 없음.
    ("edit", [_counter("c", -1, True)], {}, INSIDE),
    # R4 재생성 — 적용 규칙이 발동 목록에 없음(불변식과는 무관), 모르는 짧은 id 두 개.
    ("regenerate", [_judged("a", ["r1"], "r3", 2, False), {"unknownRuleIdCount": 2}], {"a": [1, 3]}, INSIDE),
    # R5 보내기 — 키의 폭(2)이 원소의 폭(4)과 다름 + 원소 없는 스탯의 키 → 위반 둘.
    ("send", [_judged("a", ["r1"], "r1", 4, False)], {"a": [1, 3], "b": [0, 1]}, INSIDE),
    # R6 보내기 — 잘리지 않은 0 아닌 폭인데 키 없음 → 위반.
    ("send", [_judged("a", ["r1"], "r1", 2, False)], {}, INSIDE),
    # R7 보내기 — 기록 없음인데 변화 있음(켜기 전 행을 물려받은 재생성 같은 경우). 검사 대상 아님.
    ("send", [], {"a": [1, 2]}, INSIDE),
    # R8 보내기 — 아무것도 없음.
    ("send", [], {}, INSIDE),
    # R9 보내기 — 반영 전 값이 없던 스탯(시작 값을 기록만으로 알 수 없음).
    ("send", [_judged("a", ["r1"], "r1", 1, False)], {"a": [None, 6]}, INSIDE),
    # R10 기준 시각 전 — 세지 않는다.
    ("send", [_judged("a", ["r1"], "r1", 9, False)], {}, BEFORE),
    # R11 수정 — 알 수 없는 꼴의 원소.
    ("edit", [{"shape": 1}], {}, INSIDE),
]


@pytest.fixture
async def turns() -> AsyncIterator[asyncpg.Connection]:
    url = make_url(os.environ["DATABASE_URL"])
    connection = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database=url.database
    )
    try:
        await connection.execute(
            "CREATE TEMP TABLE chat_turns (kind text NOT NULL, stat_events jsonb NOT NULL,"
            " stat_changes jsonb NOT NULL, created_at timestamptz NOT NULL)"
        )
        await connection.executemany(
            "INSERT INTO chat_turns VALUES ($1, $2::jsonb, $3::jsonb, $4)",
            [(kind, json.dumps(events), json.dumps(changes), at) for kind, events, changes, at in ROWS],
        )
        yield connection
    finally:
        await connection.close()


async def test_counts_rows_and_element_kinds_since_the_cutoff(turns: asyncpg.Connection) -> None:
    report = await stat_event_distribution(turns, since=SINCE)
    overall = report["all"]
    assert overall["turns"] == 10
    assert overall["rowsWithEvents"] == 8
    assert overall["rowsWithChanges"] == 6
    assert overall["rowsNoEventsWithChanges"] == 1
    assert overall["elements"] == {"judged": 6, "counter": 2, "unknown": 1, "other": 1}
    assert overall["unknownRuleIds"] == 2


async def test_fired_rules_per_turn_and_per_judged_element(turns: asyncpg.Connection) -> None:
    overall = (await stat_event_distribution(turns, since=SINCE))["all"]
    # 기록 있는 행만: R3·R11 은 0, R2·R4·R5·R6·R9 는 1, R1 은 2.
    assert overall["firedPerTurn"] == {"0": 2, "1": 5, "2": 1}
    assert overall["firedPerElement"] == {"1": 5, "2": 1}


async def test_clamped_rate_is_per_element_kind(turns: asyncpg.Connection) -> None:
    overall = (await stat_event_distribution(turns, since=SINCE))["all"]
    assert overall["clamped"] == {"judged": 1, "counter": 1}
    assert overall["clampedRate"] == {"judged": pytest.approx(1 / 6), "counter": pytest.approx(0.5)}


async def test_applied_rule_share_compares_the_whole_reference_pair(turns: asyncpg.Connection) -> None:
    overall = (await stat_event_distribution(turns, since=SINCE))["all"]
    assert overall["appliedInFired"] == {
        "turnsWithJudged": 6,
        "turnsAllApplied": 5,
        "turnShare": pytest.approx(5 / 6),
        "elements": 5,
    }


async def test_invariant_counts_each_kind_of_violation(turns: asyncpg.Connection) -> None:
    overall = (await stat_event_distribution(turns, since=SINCE))["all"]
    assert overall["invariant"] == {
        "rowsChecked": 8,
        "rowsViolating": 2,
        "deltaMismatch": 1,
        "clampMismatch": 0,
        "missingChange": 1,
        "changeWithoutEvent": 1,
        "malformed": 0,
        "startUnknown": 1,
    }


async def test_breaks_down_by_turn_kind(turns: asyncpg.Connection) -> None:
    report = await stat_event_distribution(turns, since=SINCE)
    assert {kind: report[kind]["turns"] for kind in ("send", "edit", "regenerate")} == {
        "send": 7,
        "edit": 2,
        "regenerate": 1,
    }
    assert report["send"]["invariant"]["rowsViolating"] == 2
    assert report["edit"]["elements"] == {"judged": 0, "counter": 1, "unknown": 0, "other": 1}
    assert report["regenerate"]["appliedInFired"]["turnsAllApplied"] == 0


async def test_a_clamped_change_must_move_with_the_delta_and_by_less_than_it(turns: asyncpg.Connection) -> None:
    await turns.execute("DELETE FROM chat_turns")
    # 거꾸로 조금 · 거꾸로 많이 · 같은 방향이지만 폭 이상 — 잘린 원소로는 셋 다 나올 수 없다.
    await turns.executemany(
        "INSERT INTO chat_turns VALUES ('send', $1::jsonb, $2::jsonb, $3)",
        [
            (json.dumps([_judged("a", ["r1"], "r1", 3, True)]), json.dumps({"a": change}), INSIDE)
            for change in ([100, 99], [100, 90], [90, 100])
        ],
    )
    invariant = (await stat_event_distribution(turns, since=SINCE))["all"]["invariant"]
    assert invariant["clampMismatch"] == 3
    assert invariant["rowsViolating"] == 3


async def test_until_bounds_the_window(turns: asyncpg.Connection) -> None:
    report = await stat_event_distribution(turns, since=BEFORE, until=SINCE)
    assert report["all"]["turns"] == 1


def test_sql_selects_only_aggregates_and_never_writes() -> None:
    sql = stat_events_sql(SINCE, None)
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "COPY", "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT"):
        assert re.search(rf"\b{verb}\b", sql, re.IGNORECASE) is None, verb
    # 방·메시지·턴 id 칸을 고르지 않는다.
    for column in ("chat_room_id", "assistant_message_id", "llm_calls"):
        assert column not in sql
    assert "2026-01-02T00:00:00+00:00" in sql


async def test_read_only_connection_refuses_writes() -> None:
    async with read_only_connection(os.environ["DATABASE_URL"]) as connection:
        with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
            await connection.execute("CREATE TEMP TABLE should_not_exist (x int)")


# ---------------------------------------------------------------- 같은 규칙의 연속 적용


def _applied(stat: str, rule: str, delta: float, clamped: bool, *, version: str = "v1") -> dict[str, Any]:
    """판정 원소 — 적용 규칙은 `entityId` 로 같은 규칙, `id` 는 판본마다 다르다."""
    ref = {"entityId": rule, "id": f"{rule}-{version}"}
    return {"statEntityId": stat, "firedRuleIds": [ref], "appliedRuleId": ref, "delta": delta, "clamped": clamped}


ROOM_1 = uuid.UUID("00000000-0000-4000-8000-000000000001")
ROOM_2 = uuid.UUID("00000000-0000-4000-8000-000000000002")


def _at(turn: int, seconds: int = 0) -> datetime:
    return INSIDE + timedelta(minutes=turn, seconds=seconds)


# (방, 턴 번호, 살아 있나, stat_events, created_at). 기대값은 아래 테스트가 손으로 센다.
REPEAT_ROWS: list[tuple[uuid.UUID, int, bool, list[Any], datetime]] = [
    # 방 1 스탯 a: 규칙 x 가 턴 1·2·3 에 연달아(턴 3 은 규칙의 다른 판본) → 길이 3, 그중 둘 잘림.
    (ROOM_1, 1, True, [_applied("a", "x", 2, False), _applied("b", "z", 1, True)], _at(1)),
    (ROOM_1, 2, True, [_applied("a", "x", 2, True), _applied("b", "z", 1, True)], _at(2)),
    # 턴 2 를 재생성하기 전 응답 — 메시지가 지워져 죽은 턴. 넣으면 위 연속이 끊긴다.
    (ROOM_1, 2, False, [_applied("a", "y", -1, False)], _at(2, -30)),
    (ROOM_1, 3, True, [_applied("a", "x", 2, True, version="v2")], _at(3)),
    # 규칙 y 가 턴 4 와 턴 6 — 턴 5 에 a 의 판정이 없어 인접하지 않으므로 길이 1 둘.
    (ROOM_1, 4, True, [_applied("a", "y", -1, False)], _at(4)),
    (ROOM_1, 5, True, [{"statEntityId": "c", "counter": True, "delta": -1, "clamped": False}], _at(5)),
    (ROOM_1, 6, True, [_applied("a", "y", -1, False)], _at(6)),
    # 방 2: 기준 시각 전 턴은 세지 않는다 — 넣으면 턴 2 와 이어져 길이 2 가 된다.
    (ROOM_2, 1, True, [_applied("a", "x", -3, False)], BEFORE),
    (ROOM_2, 2, True, [_applied("a", "x", -3, False)], _at(2)),
]


@pytest.fixture
async def repeat_turns() -> AsyncIterator[asyncpg.Connection]:
    url = make_url(os.environ["DATABASE_URL"])
    connection = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database=url.database
    )
    try:
        await connection.execute(
            "CREATE TEMP TABLE chat_turns (chat_room_id uuid NOT NULL, assistant_message_id uuid NOT NULL,"
            " turn_number integer NOT NULL, stat_events jsonb NOT NULL, created_at timestamptz NOT NULL);"
            "CREATE TEMP TABLE chat_messages (id uuid PRIMARY KEY)"
        )
        for room, turn, live, events, at in REPEAT_ROWS:
            message = uuid.uuid4()
            if live:
                await connection.execute("INSERT INTO chat_messages VALUES ($1)", message)
            await connection.execute(
                "INSERT INTO chat_turns VALUES ($1, $2, $3, $4::jsonb, $5)", room, message, turn, json.dumps(events), at
            )
        yield connection
    finally:
        await connection.close()


EXPECTED_RUNS = {"all": {"1": 3, "2": 1, "3": 1}, "pos": {"2": 1, "3": 1}, "neg": {"1": 3}}


async def test_repeat_runs_follow_the_same_rule_across_adjacent_live_turns(repeat_turns: asyncpg.Connection) -> None:
    report = await stat_repeat_distribution(repeat_turns, since=SINCE)
    assert {direction: entry["runs"] for direction, entry in report["byDirection"].items()} == EXPECTED_RUNS
    assert report["scope"] == {
        "liveTurns": 7,
        "deadTurns": 1,
        "liveTurnsWithJudged": 6,
        "rooms": 2,
        "roomStats": 3,
    }


async def test_repeat_runs_count_how_much_of_each_run_was_clamped(repeat_turns: asyncpg.Connection) -> None:
    overall = (await stat_repeat_distribution(repeat_turns, since=SINCE))["byDirection"]["all"]
    assert overall["elements"] == 8
    assert overall["clamped"] == 4
    assert overall["clampedRate"] == pytest.approx(4 / 8)
    assert overall["runClamped"] == {"1": 0, "2": 2, "3": 2}
    # 길이 2 이상(같은 규칙이 이어진 구간): 방 1 a 의 x 셋 + 방 1 b 의 z 둘.
    assert overall["repeated"] == {
        "runs": 2,
        "elements": 5,
        "clamped": 4,
        "clampedRate": pytest.approx(4 / 5),
        "elementShare": pytest.approx(5 / 8),
    }
    assert overall["longestRun"] == 3


async def test_repeat_runs_change_when_dead_turns_are_let_in(repeat_turns: asyncpg.Connection) -> None:
    """위 기대값이 죽은 턴을 가려낸다는 신호 — 살아 있는 턴 조건을 빼면 같은 데이터에서 기대값이 깨져야 한다."""
    sql = stat_repeat_sql(SINCE, None)
    assert sql.count(LIVE_FILTER) == 1
    rows = await repeat_turns.fetch(sql.replace(LIVE_FILTER, "WHERE true"))
    report = summarize_repeat_rows([tuple(row) for row in rows])
    assert {direction: entry["runs"] for direction, entry in report["byDirection"].items()} != EXPECTED_RUNS


async def test_repeat_until_bounds_the_window(repeat_turns: asyncpg.Connection) -> None:
    report = await stat_repeat_distribution(repeat_turns, since=BEFORE, until=SINCE)
    assert report["scope"]["liveTurns"] == 1
    assert report["byDirection"]["all"]["runs"] == {"1": 1}


def test_repeat_sql_selects_only_aggregates_and_never_writes() -> None:
    sql = stat_repeat_sql(SINCE, datetime(2026, 1, 9, tzinfo=UTC))
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "COPY", "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT"):
        assert re.search(rf"\b{verb}\b", sql, re.IGNORECASE) is None, verb
    # 메시지 글은 읽지 않는다 — 메시지 행은 있는지만 본다.
    assert "content" not in sql
    assert "2026-01-02T00:00:00+00:00" in sql and "2026-01-09T00:00:00+00:00" in sql


def test_repeat_sql_refuses_a_naive_time() -> None:
    with pytest.raises(SystemExit, match="시간대"):
        stat_repeat_sql(datetime(2026, 1, 2), None)
