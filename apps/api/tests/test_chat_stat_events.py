"""스탯 판정 이벤트 — 반영 함수가 값과 함께 돌려주는 이벤트 목록(`apply_rule_judgment_with_events`)이 무엇을 담는지.

규칙(결과를 보기 전에 적었다):
- 판정 스탯은 발동한 규칙이 하나라도 있을 때 원소 하나다 — 발동한 규칙 전부(작가 순서)와 적용한 규칙 하나, 그 폭, 범위에 잘렸는지.
  규칙은 `{entityId, id}` 쌍으로 가리킨다(판본을 넘어 같은 규칙 / 그 판본의 규칙 행). 조건 글은 싣지 않는다.
- 적용한 규칙은 값 반영이 고른 것과 같다(|폭| 이 가장 큰 것, 같으면 작가 순서가 앞선 것).
- 카운터 스탯은 매 턴 원소 하나(카운터 표시, 턴당 폭, 잘렸는지) — 발동 규칙 칸이 없다.
- 대응표에 없는 짧은 id 는 개수만 남긴다(원문은 남기지 않는다).
- 이벤트만으로 값이 다시 나온다: 원소가 있는 스탯은 `clamp(시작 + 폭)`, 없는 스탯은 시작 값.

전부 DB 없이 생성자로 채운 ORM 객체로 돈다."""

import uuid
from typing import Any

import pytest

from api.chat.stats import apply_rule_judgment, apply_rule_judgment_with_events
from api.db.models.story import StatDef, StatRule


def _stat(*, min_value: int = 0, max_value: int = 100, per_turn_delta: int | None = None) -> StatDef:
    return StatDef(
        entity_id=uuid.uuid4(),
        min_value=min_value,
        max_value=max_value,
        initial_value=50,
        per_turn_delta=per_turn_delta,
    )


def _rule(delta: int, order: int) -> StatRule:
    return StatRule(id=uuid.uuid4(), entity_id=uuid.uuid4(), condition="[RULE] 조건 글", delta=delta, order=order)


def _ref(rule: StatRule) -> dict[str, str]:
    return {"entityId": str(rule.entity_id), "id": str(rule.id)}


def _ids(stat: StatDef, *rules: StatRule, letter: str = "a") -> dict[str, tuple[str, StatRule]]:
    return {f"{letter}{index}": (str(stat.entity_id), rule) for index, rule in enumerate(rules, start=1)}


def _replay(events: list[dict[str, Any]], start: dict[str, float], defs: list[StatDef]) -> dict[str, float]:
    """이벤트만으로 반영 뒤 값을 다시 낸다 — 원소가 있는 스탯은 `clamp(시작 + 폭)`, 없는 스탯은 시작 값."""
    by_stat = {event["statEntityId"]: event for event in events if "statEntityId" in event}
    values: dict[str, float] = {}
    for stat in defs:
        stat_id = str(stat.entity_id)
        base = start.get(stat_id, float(stat.initial_value))
        event = by_stat.get(stat_id)
        values[stat_id] = base if event is None else min(max(base + event["delta"], stat.min_value), stat.max_value)
    return values


def test_a_judged_stat_records_every_fired_rule_and_the_one_it_applied() -> None:
    """발동한 셋 중 |폭| 이 가장 큰 -7 이 적용된다. 모델이 낸 순서(3·1·2)가 아니라 작가 순서로 적고, 적용한 규칙은 마지막에
    발동한 것이 아니다. 깨지는 시나리오: 발동 목록을 버리거나 마지막 발동을 적용한 규칙으로 적어, 폭이 같은 규칙이 둘일 때
    무엇이 값을 바꿨는지 사후에 못 가린다."""
    stat = _stat()
    small, large, middle = _rule(3, 0), _rule(-7, 1), _rule(5, 2)

    outcome = apply_rule_judgment_with_events(
        {str(stat.entity_id): 50.0}, ["a3", "a1", "a2"], _ids(stat, small, large, middle), [stat]
    )

    assert outcome.values == {str(stat.entity_id): 43.0}
    assert outcome.events == [
        {
            "statEntityId": str(stat.entity_id),
            "firedRuleIds": [_ref(small), _ref(large), _ref(middle)],
            "appliedRuleId": _ref(large),
            "delta": -7,
            "clamped": False,
        }
    ]


@pytest.mark.parametrize(
    ("deltas", "fired", "applied"),
    [
        pytest.param([5, -5], ["a2", "a1"], 0, id="tie-goes-to-earlier-order"),
        pytest.param([-5, 5], ["a1", "a2"], 0, id="tie-goes-to-earlier-order-whatever-the-listing"),
        pytest.param([2, 4], ["a2", "a1"], 1, id="larger-magnitude-listed-first"),
    ],
)
def test_the_applied_rule_is_the_one_the_value_moved_by(deltas: list[int], fired: list[str], applied: int) -> None:
    stat = _stat()
    rules = [_rule(delta, order) for order, delta in enumerate(deltas)]

    outcome = apply_rule_judgment_with_events({str(stat.entity_id): 50.0}, fired, _ids(stat, *rules), [stat])

    (event,) = outcome.events
    assert event["appliedRuleId"] == _ref(rules[applied])
    assert outcome.values[str(stat.entity_id)] == 50.0 + rules[applied].delta


@pytest.mark.parametrize(
    ("start", "delta", "value", "clamped"),
    [
        pytest.param(95.0, 10, 100.0, True, id="past-max"),
        pytest.param(5.0, -10, 0.0, True, id="past-min"),
        pytest.param(90.0, 10, 100.0, False, id="lands-on-max"),
        pytest.param(100.0, 5, 100.0, True, id="already-at-max"),
    ],
)
def test_clamped_says_whether_the_rule_ran_past_the_range(
    start: float, delta: int, value: float, clamped: bool
) -> None:
    """이미 최대인 스탯에 +5 가 적용되면 값은 그대로지만 이벤트는 남는다 — 적용됐고 잘렸다."""
    stat = _stat()
    rule = _rule(delta, 0)

    outcome = apply_rule_judgment_with_events({str(stat.entity_id): start}, ["a1"], _ids(stat, rule), [stat])

    assert outcome.values == {str(stat.entity_id): value}
    assert [(event["delta"], event["clamped"]) for event in outcome.events] == [(delta, clamped)]


@pytest.mark.parametrize(
    ("current", "clamped"),
    [pytest.param({"seeded": 1.0}, False, id="seeded"), pytest.param({"seeded": 0.0}, True, id="at-min")],
)
def test_a_counter_stat_gets_its_own_element_every_turn(current: dict[str, float], clamped: bool) -> None:
    """카운터는 발동 규칙 없이 매 턴 움직여 턴 기록의 변화에 오르므로, 그 변화를 설명하는 원소가 있어야 한다. 깨지는 시나리오:
    카운터 원소를 빼서 카운터 작품의 변화 일부가 이벤트로 설명되지 않는다."""
    days = _stat(min_value=0, max_value=30, per_turn_delta=-1)
    start = {str(days.entity_id): current["seeded"]}

    outcome = apply_rule_judgment_with_events(start, [], {}, [days])

    assert outcome.events == [{"statEntityId": str(days.entity_id), "counter": True, "delta": -1, "clamped": clamped}]


def test_unknown_short_ids_are_counted_but_not_kept() -> None:
    stat = _stat()
    rule = _rule(4, 0)

    outcome = apply_rule_judgment_with_events(
        {str(stat.entity_id): 50.0}, ["zz9", "a1", "b7", "zz9"], _ids(stat, rule), [stat]
    )

    assert outcome.events[-1] == {"unknownRuleIdCount": 2}
    assert "zz9" not in repr(outcome.events) and "b7" not in repr(outcome.events)


def test_a_turn_with_nothing_fired_and_no_counter_has_no_events() -> None:
    stat = _stat()

    assert apply_rule_judgment_with_events({str(stat.entity_id): 50.0}, [], _ids(stat, _rule(4, 0)), [stat]).events == []


def test_no_author_text_is_kept() -> None:
    stat = _stat()
    rule = _rule(4, 0)

    outcome = apply_rule_judgment_with_events({str(stat.entity_id): 50.0}, ["a1"], _ids(stat, rule), [stat])

    assert "[RULE]" not in repr(outcome.events)


@pytest.mark.parametrize(
    ("trust_start", "fired"),
    [
        pytest.param(50.0, ["a1", "a2", "b1"], id="both-stats-fire"),
        pytest.param(98.0, ["a1"], id="clamped-without-moving-past"),
        pytest.param(100.0, ["a1"], id="at-max-no-change"),
        pytest.param(50.0, [], id="nothing-fired"),
        pytest.param(50.0, ["b2", "x1"], id="other-stat-and-unknown"),
    ],
)
def test_events_alone_replay_the_values(trust_start: float, fired: list[str]) -> None:
    """판정 스탯 둘과 카운터 하나가 섞인 턴 — 이벤트만으로 값이 다시 나오고, 값 함수(`apply_rule_judgment`)와도 같다."""
    trust, mood = _stat(), _stat(min_value=-10, max_value=10)
    days = _stat(min_value=0, max_value=30, per_turn_delta=-1)
    defs = [trust, mood, days]
    rule_ids = {**_ids(trust, _rule(5, 0), _rule(-2, 1)), **_ids(mood, _rule(3, 0), _rule(-4, 1), letter="b")}
    start = {str(trust.entity_id): trust_start, str(mood.entity_id): 9.0, str(days.entity_id): 30.0}

    outcome = apply_rule_judgment_with_events(start, fired, rule_ids, defs)

    assert outcome.values == apply_rule_judgment(start, fired, rule_ids, defs)
    assert _replay(outcome.events, start, defs) == outcome.values
