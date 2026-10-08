import { stepMoveIndices, type MoveIndices } from "@/features/build-story";

/** 손잡이에서 화살표 키로 규칙을 한 칸 옮기는 이동과, 옮긴 뒤 포커스를 둘 규칙의 id. */
export type StatRuleStep = MoveIndices & { focusRuleId: string };

/**
 * `index` 의 규칙을 한 칸 위(-1)나 아래(1)로 옮긴다. 양 끝을 넘거나 모르는 자리면 undefined.
 *
 * 포커스는 옮긴 규칙을 따라간다 — 이동 전 `index` 에 있던 규칙의 id 이고, 이동 뒤 그 자리에 밀려온 이웃이 아니다. 그래야 손잡이에서
 * 화살표를 거듭 누르면 같은 규칙이 계속 움직이고, "N번째로 옮겼어요" 안내가 포커스가 있는 규칙을 말한다.
 */
export function stepStatRule(ruleIds: readonly string[], index: number, step: -1 | 1): StatRuleStep | undefined {
  const indices = stepMoveIndices(index, step, ruleIds.length);
  const focusRuleId = ruleIds[index];
  if (!indices || focusRuleId === undefined) return undefined;
  return { ...indices, focusRuleId };
}
