import uuid

from api.chat.ending_rules import evaluate_item, evaluate_rule_list
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
