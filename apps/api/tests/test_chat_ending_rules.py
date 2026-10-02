import uuid

from api.chat.ending_rules import evaluate_item, evaluate_rule_list, is_ending_check_due, referenced_stat_ids
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
