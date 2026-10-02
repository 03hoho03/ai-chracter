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
