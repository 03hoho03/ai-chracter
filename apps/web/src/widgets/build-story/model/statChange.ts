import { hasPerTurnDelta, hasStatChangeLimit, type StatDefValues } from "@/features/build-story";

/**
 * 스탯 값이 바뀌는 방식 — 턴당 자동 변화(`perTurn`)와 판정 AI 의 변화를 자르는 방향·최대 폭(`limit`)은 함께 쓸 수 없다.
 * 먼저 채운 쪽이 다른 쪽을 잠그고(잠근 칸의 값은 지우지 않는다 — 잘못 친 숫자 하나로 작가가 고른 방향·폭이 사라지지 않게),
 * 둘 다 채워진 채 들어온 값(`conflict`, 다른 기기·옛 데이터)은 어느 쪽도 잠그지 않아 한쪽을 비우면 풀린다.
 */
export type StatChangeMode = "free" | "perTurn" | "limit" | "conflict";

export function statChangeMode(
  stat: Pick<StatDefValues, "perTurnDelta" | "changeDirection" | "maxChangePerTurn">,
): StatChangeMode {
  const isPerTurn = hasPerTurnDelta(stat);
  const isLimited = hasStatChangeLimit(stat);
  if (isPerTurn && isLimited) return "conflict";
  if (isPerTurn) return "perTurn";
  if (isLimited) return "limit";
  return "free";
}

/**
 * 한 턴 최대 폭 입력칸의 값을 폼 값으로 바꾼다. 빈 칸은 제한 없음(null)이다. 정수가 아닌 값은 NaN 으로 두어 폼 검증이
 * 칸에 오류를 붙이게 하고, 자동저장은 그 값을 보내지 않아 서버에 저장된 폭을 그대로 둔다(서버는 정수가 아닌 값이 든 초안을
 * 통째로 거절한다).
 * 0·음수는 저장은 되고 발행 전에 폼 검증이 막는다.
 */
export function maxChangePerTurnFromInput(value: unknown): number | null {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : Number.NaN;
}

/** 한 턴 최대 폭 칸에서 아예 받지 않는 글자 — 음수·소수·지수 표기. `type="number"` 입력칸은 이 글자들을 받아들인다. */
const BLOCKED_MAX_CHANGE_KEYS = new Set(["-", "+", ".", ",", "e", "E"]);

export function isBlockedMaxChangeKey(key: string): boolean {
  return BLOCKED_MAX_CHANGE_KEYS.has(key);
}

/** 한 턴 최대 폭 칸에 붙여 넣지 않는 글 — 숫자만으로 된 글이 아니면 막는다. 키 차단은 붙여 넣기를 거치지 않는다. */
export function isBlockedMaxChangePaste(text: string): boolean {
  return !/^\d+$/.test(text);
}
