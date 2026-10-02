import type { RuleListItemValues } from "./schema";

/**
 * 스탯을 지울 때 그 스탯을 가리키는 엔딩 규칙도 함께 지운다. 남겨 두면 규칙 줄은 빈칸으로 보이고, 서버는 없는 스탯을
 * 가리키는 규칙이 든 초안의 저장을 거절해 그 뒤 자동저장이 통째로 멈춘다.
 *
 * 그룹 안의 규칙도 같이 지운다. 규칙이 전부 지워져 비게 된 그룹은 그룹째 지운다 — 빈 그룹은 참으로 평가되므로 남겨 두면
 * `(지운 스탯 조건) or 다른 조건` 이 언제나 참이 된다. 작가가 처음부터 비워 둔 그룹은 이 삭제와 무관하므로 건드리지 않는다.
 * 지울 것이 없으면 받은 배열을 그대로 돌려줘 호출부가 쓰기를 건너뛸 수 있게 한다.
 */
export function removeRulesReferencingStat(items: RuleListItemValues[], statId: string): RuleListItemValues[] {
  let changed = false;
  const next: RuleListItemValues[] = [];
  for (const item of items) {
    if (item.kind === "rule") {
      if (item.statId === statId) changed = true;
      else next.push(item);
      continue;
    }
    const rules = item.rules.filter((rule) => rule.statId !== statId);
    if (rules.length === item.rules.length) {
      next.push(item);
      continue;
    }
    changed = true;
    if (rules.length > 0) next.push({ ...item, rules });
  }
  return changed ? next : items;
}

type StatRemovalRuleUpdate = { endingIndex: number; statRules: RuleListItemValues[] };

/** 그 스탯을 가리키는 엔딩 조건 수. 그룹 안의 조건도 하나씩 센다. */
function countRulesReferencingStat(items: RuleListItemValues[], statId: string): number {
  let count = 0;
  for (const item of items) {
    if (item.kind === "rule") count += item.statId === statId ? 1 : 0;
    else count += item.rules.filter((rule) => rule.statId === statId).length;
  }
  return count;
}

/**
 * 스탯 하나를 지우기 전에 같은 시작설정의 엔딩들에서 함께 지울 조건을 정한다. 함께 지워질 조건이 있으면 작가가 모른 채
 * 엔딩 조건을 잃지 않도록 그 수를 들고 먼저 묻고, 거절하면 `undefined` 를 돌려줘 호출부가 스탯도 조건도 건드리지 않게 한다.
 * 조건이 없으면 묻지 않고 빈 목록을 돌려준다. 바뀌는 엔딩만 담는다.
 */
export async function planStatRemoval(
  endings: { statRules: RuleListItemValues[] }[],
  statId: string,
  confirm: (ruleCount: number) => Promise<boolean>,
): Promise<StatRemovalRuleUpdate[] | undefined> {
  const ruleCount = endings.reduce((sum, ending) => sum + countRulesReferencingStat(ending.statRules, statId), 0);
  if (ruleCount > 0 && !(await confirm(ruleCount))) return undefined;
  const updates: StatRemovalRuleUpdate[] = [];
  endings.forEach((ending, endingIndex) => {
    const statRules = removeRulesReferencingStat(ending.statRules, statId);
    if (statRules !== ending.statRules) updates.push({ endingIndex, statRules });
  });
  return updates;
}
