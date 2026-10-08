import { hasPerTurnDelta, type StatDefValues } from "@/features/build-story";

/**
 * 스탯 값이 바뀌는 방식 — 턴당 자동 변화(`perTurn`)와 판정 AI 가 고르는 규칙(`rules`)은 함께 쓸 수 없다. 턴당 자동 변화가
 * 있는 스탯은 판정을 받지 않아 규칙이 발동할 일이 없다. 먼저 채운 쪽이 다른 쪽을 잠그고(잠근 칸의 값은 지우지 않는다), 둘 다
 * 채워진 채 들어온 값(`conflict`, 다른 기기·옛 데이터)은 어느 쪽도 잠그지 않아 한쪽을 비우면 풀린다.
 */
export type StatChangeMode = "free" | "perTurn" | "rules" | "conflict";

export function statChangeMode(stat: Pick<StatDefValues, "perTurnDelta" | "rules">): StatChangeMode {
  const isPerTurn = hasPerTurnDelta(stat);
  const hasRules = stat.rules.length > 0;
  if (isPerTurn && hasRules) return "conflict";
  if (isPerTurn) return "perTurn";
  if (hasRules) return "rules";
  return "free";
}

/**
 * 규칙 증감 입력칸의 글을 폼 값으로 바꾼다. 부호는 숫자 앞에 직접 적는다(`+3`·`-5`, 부호 없는 `3` 도 받는다). 빈 칸과 정수로
 * 읽히지 않는 글은 NaN 이다 — 폼 검증이 칸에 오류를 붙이고, 자동저장은 그 규칙 하나만 빼고 같은 스탯의 나머지 규칙을 보낸다
 * (이미 저장된 규칙이면 다시 읽히는 값이 될 때까지 서버에서 빠진다). 수학 기호 빼기(−)와 전각 부호도 받는다(한글 자판·붙여 넣기로 들어온다).
 */
export function statRuleDeltaFromInput(text: string): number {
  const normalized = text.trim().replace(/[−－]/g, "-").replace(/＋/g, "+");
  return /^[+-]?\d+$/.test(normalized) ? Number(normalized) : Number.NaN;
}

/** 폼 값을 증감 입력칸 글로 — 양수에도 부호를 붙여 "오르는 규칙"이 한눈에 보이게 한다. NaN 은 빈 칸. */
export function formatStatRuleDelta(delta: number): string {
  if (!Number.isFinite(delta)) return "";
  return delta > 0 ? `+${delta}` : String(delta);
}

/**
 * 증감 칸 아래 입력 중 안내. 발행을 막는 오류 문장은 폼 검증이 붙이고(그때는 그쪽이 보인다), 이 문장은 저장을 막지 않고 미리
 * 알린다. 범위 폭은 최대 − 최소이고, 범위가 아직 맞지 않으면(빈 칸·뒤집힘) 폭 경고는 하지 않는다.
 */
export function statRuleDeltaHint(text: string, delta: number, range: { min: number; max: number }): string | undefined {
  if (text.trim() === "") return undefined;
  if (Number.isNaN(delta)) return "+3, -5처럼 부호와 정수로 적어 주세요.";
  if (delta === 0) return "0은 값을 바꾸지 않아요. 0이 아닌 정수를 적어 주세요.";
  const width = range.max - range.min;
  if (Number.isFinite(width) && width > 0 && Math.abs(delta) > width) {
    return `이 스탯의 범위 폭(${width})보다 커서 발행할 수 없어요. ${width} 이하로 줄여 주세요.`;
  }
  return undefined;
}
