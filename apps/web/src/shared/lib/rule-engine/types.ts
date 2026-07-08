// techspec-builder-story.md §1.5 — 엔딩 스탯 규칙(단일 규칙/그룹, and/or 누적)의 타입과 평가
// 순수 함수. BE 포팅은 apps/api/src/api/chat/ending_rules.py의 evaluate_item/evaluate_rule_list.
// 빌더(US-091~)/미리보기(US-089)와 entities/chat-room(US-052 provisional 타입)이 공유하는
// 단일 진실 공급원이다.

export type ComparisonOp = ">" | ">=" | "<" | "<=" | "==" | "!=";
export type LogicOp = "and" | "or";

// 단일 규칙: 스탯 하나를 연산자/기준값으로 비교
export type SingleRule = {
  kind: "rule";
  id: string;
  statId: string;
  operator: ComparisonOp;
  value: number;
  nextOp: LogicOp | null; // 다음 항목과의 관계. 목록의 마지막 항목이면 null(무시)
};

// 규칙 그룹: 내부에 단일 규칙만 포함(그룹 중첩 불가, FR-59)
export type RuleGroup = {
  kind: "group";
  id: string;
  rules: SingleRule[]; // 그룹 내부도 동일한 nextOp 누적 평가
  nextOp: LogicOp | null;
};

export type RuleListItem = SingleRule | RuleGroup;

function compare(statValue: number, operator: ComparisonOp, value: number): boolean {
  switch (operator) {
    case ">":
      return statValue > value;
    case ">=":
      return statValue >= value;
    case "<":
      return statValue < value;
    case "<=":
      return statValue <= value;
    case "==":
      return statValue === value;
    case "!=":
      return statValue !== value;
  }
}

export function evaluateItem(item: RuleListItem, statValues: Record<string, number>): boolean {
  if (item.kind === "rule") {
    return compare(statValues[item.statId] ?? 0, item.operator, item.value);
  }
  return evaluateRuleList(item.rules, statValues); // 그룹 내부도 동일 알고리즘 재귀 적용
}

export function evaluateRuleList(items: RuleListItem[], statValues: Record<string, number>): boolean {
  const [first, ...rest] = items;
  if (!first) return true; // 규칙 없으면 항상 통과(판단 프롬프트만으로 판정)

  let result = evaluateItem(first, statValues);
  let previous = first;
  for (const item of rest) {
    const current = evaluateItem(item, statValues);
    result = previous.nextOp === "or" ? result || current : result && current; // 이전 항목의 nextOp로 누적
    previous = item;
  }
  return result;
}
