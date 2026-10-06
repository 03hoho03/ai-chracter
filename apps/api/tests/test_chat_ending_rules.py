import uuid

from api.chat.ending_rules import (
    EndingCandidate,
    ending_judgment_order,
    evaluate_item,
    evaluate_rule_list,
    is_ending_check_due,
    referenced_stat_ids,
)
from api.chat.schemas import EndingRuleGroupItem, EndingRuleItem, EndingRuleListItem
from api.db.models.story import EndingRuleOperator, LogicalOp


def _rule(
    stat_id: uuid.UUID,
    operator: EndingRuleOperator,
    threshold: float,
    next_op: LogicalOp | None = None,
) -> EndingRuleItem:
    return EndingRuleItem(id=uuid.uuid4(), stat_id=stat_id, operator=operator, threshold=threshold, next_op=next_op)


def test_evaluate_rule_list_empty_is_always_true() -> None:
    assert evaluate_rule_list([], {}) is True


def test_evaluate_item_gte_operator() -> None:
    affection = uuid.uuid4()
    rule = _rule(affection, EndingRuleOperator.GTE, 50)

    assert evaluate_item(rule, {str(affection): 50}) is True
    assert evaluate_item(rule, {str(affection): 49}) is False


def test_evaluate_item_lte_operator() -> None:
    tension = uuid.uuid4()
    rule = _rule(tension, EndingRuleOperator.LTE, 10)

    assert evaluate_item(rule, {str(tension): 10}) is True
    assert evaluate_item(rule, {str(tension): 11}) is False


def test_evaluate_item_eq_operator() -> None:
    affection = uuid.uuid4()
    rule = _rule(affection, EndingRuleOperator.EQ, 0)

    assert evaluate_item(rule, {str(affection): 0}) is True
    assert evaluate_item(rule, {str(affection): 1}) is False


def test_evaluate_item_gt_operator() -> None:
    affection = uuid.uuid4()
    rule = _rule(affection, EndingRuleOperator.GT, 50)

    assert evaluate_item(rule, {str(affection): 51}) is True
    assert evaluate_item(rule, {str(affection): 50}) is False


def test_evaluate_item_lt_operator() -> None:
    tension = uuid.uuid4()
    rule = _rule(tension, EndingRuleOperator.LT, 10)

    assert evaluate_item(rule, {str(tension): 9}) is True
    assert evaluate_item(rule, {str(tension): 10}) is False


def test_evaluate_rule_list_and_requires_all_true() -> None:
    affection = uuid.uuid4()
    tension = uuid.uuid4()
    items = [
        _rule(affection, EndingRuleOperator.GTE, 50, next_op=LogicalOp.AND),
        _rule(tension, EndingRuleOperator.LTE, 10, next_op=None),
    ]

    assert evaluate_rule_list(items, {str(affection): 60, str(tension): 5}) is True
    assert evaluate_rule_list(items, {str(affection): 60, str(tension): 20}) is False


def test_evaluate_rule_list_or_requires_any_true() -> None:
    affection = uuid.uuid4()
    tension = uuid.uuid4()
    items = [
        _rule(affection, EndingRuleOperator.GTE, 90, next_op=LogicalOp.OR),
        _rule(tension, EndingRuleOperator.LTE, 10, next_op=None),
    ]

    assert evaluate_rule_list(items, {str(affection): 10, str(tension): 5}) is True
    assert evaluate_rule_list(items, {str(affection): 95, str(tension): 999}) is True
    assert evaluate_rule_list(items, {str(affection): 10, str(tension): 999}) is False


def test_evaluate_rule_list_mixed_and_or_accumulates_left_to_right() -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    c = uuid.uuid4()
    # (a >= 50 AND b >= 50) OR c >= 50 — left-to-right accumulation, no operator precedence.
    items = [
        _rule(a, EndingRuleOperator.GTE, 50, next_op=LogicalOp.AND),
        _rule(b, EndingRuleOperator.GTE, 50, next_op=LogicalOp.OR),
        _rule(c, EndingRuleOperator.GTE, 50, next_op=None),
    ]

    assert evaluate_rule_list(items, {str(a): 100, str(b): 100, str(c): 0}) is True
    assert evaluate_rule_list(items, {str(a): 100, str(b): 0, str(c): 100}) is True
    assert evaluate_rule_list(items, {str(a): 100, str(b): 0, str(c): 0}) is False


def test_evaluate_rule_list_with_nested_group() -> None:
    affection = uuid.uuid4()
    tension = uuid.uuid4()
    trust = uuid.uuid4()
    group = EndingRuleGroupItem(
        id=uuid.uuid4(),
        rules=[
            _rule(tension, EndingRuleOperator.LTE, 10, next_op=LogicalOp.OR),
            _rule(trust, EndingRuleOperator.GTE, 80, next_op=None),
        ],
        next_op=None,
    )
    # affection >= 50 AND (tension <= 10 OR trust >= 80)
    items: list[EndingRuleListItem] = [
        _rule(affection, EndingRuleOperator.GTE, 50, next_op=LogicalOp.AND),
        group,
    ]

    assert evaluate_rule_list(items, {str(affection): 60, str(tension): 5, str(trust): 0}) is True
    assert evaluate_rule_list(items, {str(affection): 60, str(tension): 20, str(trust): 90}) is True
    assert evaluate_rule_list(items, {str(affection): 60, str(tension): 20, str(trust): 0}) is False
    assert evaluate_rule_list(items, {str(affection): 10, str(tension): 5, str(trust): 90}) is False


def test_evaluate_item_on_missing_stat_is_false_even_where_zero_would_pass() -> None:
    """값이 없는 스탯을 0 으로 읽으면 `<= 10` 이 참이 된다 — 없는 스탯은 어떤 비교에서도 거짓이다."""
    missing = uuid.uuid4()

    assert evaluate_item(_rule(missing, EndingRuleOperator.LTE, 10), {}) is False
    assert evaluate_item(_rule(missing, EndingRuleOperator.GTE, 0), {}) is False


def test_evaluate_rule_list_missing_stat_is_one_false_item_not_a_failed_list() -> None:
    """없는 스탯은 그 항목만 거짓이라 OR 로 이어진 다른 항목이 참이면 목록은 참이다."""
    missing = uuid.uuid4()
    affection = uuid.uuid4()
    items = [
        _rule(missing, EndingRuleOperator.GTE, 0, next_op=LogicalOp.OR),
        _rule(affection, EndingRuleOperator.GTE, 50, next_op=None),
    ]

    assert evaluate_rule_list(items, {str(affection): 60}) is True
    assert evaluate_rule_list(items, {str(affection): 40}) is False


def test_referenced_stat_ids_includes_rules_inside_groups() -> None:
    """없는 스탯 경고는 이 집합으로 고른다 — 그룹 안 규칙이 빠지면 그 스탯은 경고 없이 거짓이 된다."""
    top = uuid.uuid4()
    nested = uuid.uuid4()
    group = EndingRuleGroupItem(id=uuid.uuid4(), rules=[_rule(nested, EndingRuleOperator.GTE, 1)], next_op=None)

    assert referenced_stat_ids([_rule(top, EndingRuleOperator.GTE, 1, next_op=LogicalOp.AND), group]) == {
        str(top),
        str(nested),
    }


def test_is_ending_check_due_before_gate_is_false() -> None:
    assert is_ending_check_due(9, 10) is False


def test_is_ending_check_due_at_gate_is_true() -> None:
    assert is_ending_check_due(10, 10) is True


def test_is_ending_check_due_every_five_turns_after_gate() -> None:
    assert is_ending_check_due(15, 10) is True
    assert is_ending_check_due(20, 10) is True


def test_is_ending_check_due_off_cycle_turns_after_gate_are_false() -> None:
    assert is_ending_check_due(11, 10) is False
    assert is_ending_check_due(14, 10) is False


def test_is_ending_check_due_with_gate_not_a_multiple_of_five() -> None:
    """뮤테이션: ending_rules.py:40 의 `(turn - gate) % 5`를 `(turn + gate) % 5`로
    바꿔도 기존 4개 테스트가 전부 통과했다 — 전부 `gate=10`이고 `2×10 mod 5 == 0`이라 `-`와
    `+`가 모든 turn에서 같은 값을 냈다(항진명제). 5의 배수가 아닌 gate(12)로 구분한다.
    """
    assert is_ending_check_due(11, 12) is False
    assert is_ending_check_due(12, 12) is True
    assert is_ending_check_due(17, 12) is True
    assert is_ending_check_due(13, 12) is False


# 판정 순서. 엔딩은 이름 문자열로 대신한다 — 순서 함수는 엔딩 객체를 들여다보지 않고 되돌려 주기만 한다.
_DOHEE, _YUNA, _SEBIN = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _candidate(name: str, priority_stat_id: uuid.UUID | None = None) -> EndingCandidate[str]:
    return EndingCandidate(ending=name, ending_id=uuid.uuid4(), priority_stat_id=priority_stat_id)


def _routes() -> list[EndingCandidate[str]]:
    """루트 셋을 목록 순서(도희 → 유나 → 세빈)로. 우선 스탯은 각자의 호감이다."""
    return [_candidate("도희", _DOHEE), _candidate("유나", _YUNA), _candidate("세빈", _SEBIN)]


def test_ending_judgment_order_judges_only_the_highest_priority_value_in_the_group() -> None:
    """세 루트가 함께 규칙을 넘었고 세빈 100·도희 98·유나 86 이면 목록 맨 뒤의 세빈만 판정한다. 판정이 아니오여도
    도희·유나로 내려가지 않으므로 목록에 둘이 없어야 한다."""
    order = ending_judgment_order(_routes(), {str(_SEBIN): 100, str(_DOHEE): 98, str(_YUNA): 86})

    assert order.endings == ["세빈"]
    assert order.missing_priority == []


def test_ending_judgment_order_judges_tied_highest_values_in_list_order() -> None:
    """세빈과 도희가 100 으로 같으면 둘을 목록 순서(도희 → 세빈)로 판정하고, 더 낮은 유나는 빠진다."""
    order = ending_judgment_order(_routes(), {str(_SEBIN): 100, str(_DOHEE): 100, str(_YUNA): 86})

    assert order.endings == ["도희", "세빈"]


def test_ending_judgment_order_places_group_at_its_first_member_and_ends_the_list_there() -> None:
    """무리는 무리 가운데 목록상 가장 앞선 엔딩(도희)의 자리에 선다 — 그래서 앞의 우선 스탯 없는 "처음" 이 먼저다.
    무리 뒤의 "노말" 은 넣지 않는다. 1등이 아니오여도 그 턴에 노말 엔딩으로 떨어지면 안 되기 때문이다."""
    candidates = [
        _candidate("처음"),
        _candidate("도희", _DOHEE),
        _candidate("노말"),
        _candidate("세빈", _SEBIN),
    ]

    order = ending_judgment_order(candidates, {str(_SEBIN): 100, str(_DOHEE): 90})

    assert order.endings == ["처음", "세빈"]


def test_ending_judgment_order_treats_valueless_priority_stat_as_no_priority() -> None:
    """우선 스탯 값이 없는 엔딩(스탯을 지운 초안)은 무리에서 빠져 우선 스탯이 없는 엔딩처럼 제자리에 서고, 호출부가
    경고하도록 따로 돌려준다. 값을 0 으로 읽어 무리에 넣으면 판정 목록에서 사라진다."""
    missing = _candidate("지워진 스탯", uuid.uuid4())
    candidates = [missing, _candidate("도희", _DOHEE), _candidate("세빈", _SEBIN)]

    order = ending_judgment_order(candidates, {str(_SEBIN): 100, str(_DOHEE): 90})

    assert order.endings == ["지워진 스탯", "세빈"]
    assert order.missing_priority == [missing]


def test_ending_judgment_order_without_any_priority_keeps_the_list_order() -> None:
    """우선 스탯을 하나도 안 채운 작품은 받은 순서 그대로다(지금까지의 동작)."""
    candidates = [_candidate("가"), _candidate("나"), _candidate("다")]

    assert ending_judgment_order(candidates, {str(_SEBIN): 100}).endings == ["가", "나", "다"]
    assert ending_judgment_order([], {}).endings == []
