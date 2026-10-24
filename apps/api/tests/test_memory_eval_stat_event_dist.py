"""판정 이벤트 로그(`chat_turns.stat_events`) 분포 집계 — 합성 행으로 원소 종류·발동 수·잘림·적용 규칙·행마다의 일치 불변식을
센다. 실제 `chat_turns` 대신 같은 이름의 임시 테이블을 세션에 만들어(임시 스키마가 먼저 찾아진다) 집계 SQL 을 그대로 돌린다."""

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from memory_eval.stat_event_dist import read_only_connection, stat_event_distribution, stat_events_sql

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


async def test_clamped_change_against_the_delta_direction_is_a_violation(turns: asyncpg.Connection) -> None:
    await turns.execute("DELETE FROM chat_turns")
    await turns.execute(
        "INSERT INTO chat_turns VALUES ('send', $1::jsonb, $2::jsonb, $3)",
        json.dumps([_judged("a", ["r1"], "r1", 3, True)]),
        json.dumps({"a": [100, 90]}),
        INSIDE,
    )
    invariant = (await stat_event_distribution(turns, since=SINCE))["all"]["invariant"]
    assert invariant["clampMismatch"] == 1
    assert invariant["rowsViolating"] == 1


async def test_until_bounds_the_window(turns: asyncpg.Connection) -> None:
    report = await stat_event_distribution(turns, since=BEFORE, until=SINCE)
    assert report["all"]["turns"] == 1


def test_sql_selects_only_aggregates_and_never_writes() -> None:
    sql = stat_events_sql(SINCE, None)
    upper = sql.upper()
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "COPY", "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT"):
        assert verb not in upper
    # 방·메시지·턴 id 칸을 고르지 않는다.
    for column in ("chat_room_id", "assistant_message_id", "llm_calls"):
        assert column not in sql
    assert "2026-01-02T00:00:00+00:00" in sql


async def test_read_only_connection_refuses_writes() -> None:
    async with read_only_connection(os.environ["DATABASE_URL"]) as connection:
        with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
            await connection.execute("CREATE TEMP TABLE should_not_exist (x int)")
