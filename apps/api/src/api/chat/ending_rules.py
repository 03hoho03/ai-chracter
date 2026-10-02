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
    """FE `endingRules.ts`의 `evaluateItem`과 같은 알고리즘. 그룹은 내부 rules에 동일
    알고리즘(evaluate_rule_list)을 재귀 적용한다(1단계 중첩만 허용).

    값이 없는 스탯을 가리키는 항목은 어떤 연산자든 거짓이다(FE 도 같다). 규칙 참조에는 FK 가 없어, 스탯을 지운
    초안·미리보기 페이로드에서 그런 규칙이 올 수 있다. 0 으로 읽으면 `<= 10` 같은 조건이 저절로 참이 되고,
    예외로 두면 그 턴의 SSE 가 끊긴다. 경고 로그는 방·엔딩을 아는 호출부가 남긴다."""
    if isinstance(item, EndingRuleGroupItem):
        return evaluate_rule_list(item.rules, stat_values)
    value = stat_values.get(str(item.stat_id))
    if value is None:
        return False
    return _COMPARATORS[item.operator](value, item.threshold)


def referenced_stat_ids(items: Sequence[EndingRuleListItem]) -> set[str]:
    """규칙 트리(그룹 안까지)가 가리키는 스탯 id — 호출부가 값이 없는 것을 골라 경고할 때 쓴다."""
    stat_ids: set[str] = set()
    for item in items:
        if isinstance(item, EndingRuleGroupItem):
            stat_ids |= referenced_stat_ids(item.rules)
        else:
            stat_ids.add(str(item.stat_id))
    return stat_ids


def evaluate_rule_list(items: Sequence[EndingRuleListItem], stat_values: dict[str, float]) -> bool:
    """FE `endingRules.ts`의 `evaluateRuleList`와 같은 알고리즘. 비어있으면 True(judgmentPrompt만으로
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
    """turn_count_gate(최소 10)를 넘긴 시점부터 5턴마다만 엔딩 판정을 호출하고,
    그 외 턴은 스킵한다."""
    return turn_count >= turn_count_gate and (turn_count - turn_count_gate) % 5 == 0
