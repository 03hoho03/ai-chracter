import type { ReplyFlagsView, TurnMetrics } from "@/shared/api/client";

import type { BOOLEAN_FLAG_KEYS } from "./detailLabels";

/** 런 요약이 세는 응답 플래그 — 참/거짓 플래그와 깨짐·괄호. */
export type RunFlagKey = (typeof BOOLEAN_FLAG_KEYS)[number] | "broken" | "brackets";

/**
 * 그 플래그가 선 턴 번호(런 지표의 턴 칸 순서). 판정은 측정 서버가 낸 턴 칸을 그대로 읽는다 — 런 요약의 셈과 같은 기준이어야 수와
 * 목록이 맞는다(깨짐은 까닭이 있으면, 괄호는 하나라도 있으면).
 */
export function flaggedTurns(turns: ReadonlyArray<TurnMetrics>, key: RunFlagKey): number[] {
  return turns.filter((entry) => isRaised(entry.flags, key)).map((entry) => entry.turn);
}

function isRaised(flags: ReplyFlagsView, key: RunFlagKey): boolean {
  if (key === "broken") return flags.broken !== null;
  if (key === "brackets") return flags.brackets.length > 0;
  return flags[key];
}
