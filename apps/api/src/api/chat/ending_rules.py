import operator
from collections.abc import Callable, Sequence

from api.chat.schemas import EndingRuleGroupItem, EndingRuleItem, EndingRuleListItem
from api.db.models.story import EndingRuleOperator, LogicalOp

_COMPARATORS: dict[EndingRuleOperator, Callable[[float, float], bool]] = {
    EndingRuleOperator.GTE: operator.ge,
    EndingRuleOperator.LTE: operator.le,
    EndingRuleOperator.EQ: operator.eq,
    EndingRuleOperator.GT: operator.gt,
    EndingRuleOperator.LT: operator.lt,
}


def evaluate_item(item: EndingRuleListItem, stat_values: dict[str, float]) -> bool:
    """techspec-builder-story.md §1.5 evaluateItem 포팅. 그룹은 내부 rules에 동일
    알고리즘(evaluate_rule_list)을 재귀 적용한다(1단계 중첩만 허용, FR-59)."""
    if isinstance(item, EndingRuleGroupItem):
        return evaluate_rule_list(item.rules, stat_values)
    return _COMPARATORS[item.operator](stat_values[str(item.stat_id)], item.threshold)


def evaluate_rule_list(items: Sequence[EndingRuleListItem], stat_values: dict[str, float]) -> bool:
    """techspec-builder-story.md §1.5 evaluateRuleList 포팅. 비어있으면 True(judgmentPrompt만으로
    판정), 그 외엔 각 항목의 next_op(and/or)로 좌에서 우로 순차 누적한다."""
    if not items:
        return True
    result = evaluate_item(items[0], stat_values)
    for i in range(1, len(items)):
        prev_op = items[i - 1].next_op
        current = evaluate_item(items[i], stat_values)
        result = (result or current) if prev_op == LogicalOp.OR else (result and current)
    return result


def is_ending_check_due(turn_count: int, turn_count_gate: int) -> bool:
    """FR-58 — turn_count_gate(최소 10)를 넘긴 시점부터 5턴마다만 엔딩 판정을 호출하고,
    그 외 턴은 스킵한다."""
    return turn_count >= turn_count_gate and (turn_count - turn_count_gate) % 5 == 0
