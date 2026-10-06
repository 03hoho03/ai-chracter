import operator
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

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


_EndingT = TypeVar("_EndingT")


@dataclass(frozen=True)
class EndingCandidate(Generic[_EndingT]):
    """이번 턴 판정 차례이고 스탯 규칙을 통과한 엔딩 하나. `ending` 은 호출부의 엔딩 객체(실채팅은 ORM 행, 미리보기는
    초안 항목)를 그대로 되돌려 주려고 싣는다."""

    ending: _EndingT
    ending_id: uuid.UUID
    priority_stat_id: uuid.UUID | None


@dataclass(frozen=True)
class EndingJudgmentOrder(Generic[_EndingT]):
    """`endings` 는 판정할 순서다 — 호출부는 차례로 판정 모델을 부르고 처음 발동한 엔딩에서 멈추며, 끝까지 발동이
    없으면 그 턴은 엔딩 없이 끝난다. `missing_priority` 는 우선 스탯 값이 없어 무리에서 빠진 엔딩이다(호출부가 경고를
    남긴다)."""

    endings: list[_EndingT]
    missing_priority: list[EndingCandidate[_EndingT]] = field(default_factory=list)


def ending_judgment_order(
    candidates: Sequence[EndingCandidate[_EndingT]], stat_values: Mapping[str, float]
) -> EndingJudgmentOrder[_EndingT]:
    """규칙을 통과한 엔딩(목록 순서)에서 이번 턴에 판정할 엔딩과 그 순서를 정한다. 실채팅·미리보기가 함께 쓴다.

    우선 스탯이 있는 엔딩들은 한 무리로 묶여, 무리 가운데 목록상 가장 앞선 엔딩의 자리에 그 스탯 값(이번 턴 반영 뒤)이
    가장 높은 엔딩만 선다. 같은 값이면 그 엔딩들을 목록 순서대로 둔다. 목록 순서만으로 정하면 호감이 가장 높은 루트가
    아니라 목록 위쪽 루트가 열리기 때문이다. 무리가 서면 판정 목록은 거기서 끝난다 — 무리의 나머지도, 무리 자리 뒤의
    엔딩(우선 스탯이 없는 노말 엔딩 등)도 넣지 않는다. 1등이 모두 아니오면 그 턴은 엔딩 없이 끝나고 다음 판정 차례에
    다시 본다. 판정 한 번의 거절로 낮은 루트나 노말 엔딩으로 떨어지지 않게 하려는 것이다.

    무리 자리 앞의 우선 스탯 없는 엔딩은 목록 순서대로 먼저 판정된다. 무리가 서지 않는 턴(우선 스탯을 채운 엔딩이 하나도
    규칙을 통과하지 않음)은 받은 순서 그대로다 — 우선 스탯을 하나도 채우지 않은 작품은 지금까지와 같다.

    우선 스탯 값이 없으면(스탯을 지운 초안 등) 그 엔딩은 무리에서 빼고 우선 스탯이 없는 엔딩처럼 다룬다. 규칙 평가기가
    값 없는 스탯을 거짓으로 보는 것과 같은 방향이다 — 0 으로 읽어 무리에 넣으면 그 엔딩은 말없이 판정 목록에서 사라진다.

    판정할 엔딩 수는 많아야 받은 엔딩 수다."""

    def priority_value(candidate: EndingCandidate[_EndingT]) -> float | None:
        if candidate.priority_stat_id is None:
            return None
        return stat_values.get(str(candidate.priority_stat_id))

    missing = [c for c in candidates if c.priority_stat_id is not None and priority_value(c) is None]
    group_values = [value for value in map(priority_value, candidates) if value is not None]
    endings: list[_EndingT] = []
    for candidate in candidates:
        if priority_value(candidate) is None:
            endings.append(candidate.ending)
            continue
        # 무리의 첫 엔딩 자리에서 최고값(동점 포함)만 목록 순서로 세우고 목록을 끝낸다.
        top_value = max(group_values)
        endings += [c.ending for c in candidates if priority_value(c) == top_value]
        break
    return EndingJudgmentOrder(endings=endings, missing_priority=missing)
