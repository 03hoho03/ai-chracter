import type { RuleListItemValues } from "./schema";

/**
 * 조건이 같은 시작설정의 스탯 목록에 없는 스탯을 가리키는가. 이 화면에서 스탯을 지우면 그 조건도 함께 지워지므로, 이런 조건은
 * 그 처리 전에 저장된 초안이나 다른 기기에서 고친 초안에서만 들어온다. 서버는 이런 조건이 든 초안의 저장을 거절하므로 편집기가
 * '지워진 스탯'으로 드러내 작가가 고치거나 지울 수 있게 한다.
 */
export function isMissingStat(statId: string, stats: readonly { id: string }[]): boolean {
  return !stats.some((stat) => stat.id === statId);
}

/** 목록(그룹 안 포함)에 지워진 스탯을 가리키는 조건이 하나라도 있는가 — 접힌 머리 줄의 경고 표시 재료. */
export function hasRuleWithMissingStat(items: RuleListItemValues[], stats: readonly { id: string }[]): boolean {
  return items.some((item) =>
    item.kind === "rule"
      ? isMissingStat(item.statId, stats)
      : item.rules.some((rule) => isMissingStat(rule.statId, stats)),
  );
}
