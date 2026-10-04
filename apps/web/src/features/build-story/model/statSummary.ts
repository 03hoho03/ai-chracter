import { STAT_CHANGE_DIRECTION_LABELS } from "./fieldOptions";
import type { StatDefValues } from "./schema";

/** 접힌 스탯 머리 줄 요약의 글 조각. 빌더 스탯 카드와 작성 가이드의 카드 모양 예시가 같이 쓴다. 비었거나 숫자가 아닌 칸의 조각은 없다. */
export type StatSummaryParts = {
  /** 범위와 단위(`0~20일`). 단위는 범위에만 붙인다 — 초기값은 같은 단위라 반복하면 줄만 길어진다. */
  range?: string;
  initial?: string;
  perTurn?: string;
  /** 변화 방향(오르내림이 아닐 때)과 한 턴 최대 폭(`내리기만 · 최대 7`). 폭에도 단위를 붙이지 않는다. */
  limit?: string;
};

export function statSummaryParts(
  stat: Pick<
    StatDefValues,
    "min" | "max" | "initial" | "unit" | "perTurnDelta" | "changeDirection" | "maxChangePerTurn"
  >,
): StatSummaryParts {
  const { min, max, initial, perTurnDelta, changeDirection, maxChangePerTurn } = stat;
  const unit = stat.unit?.trim() ?? "";
  const parts: StatSummaryParts = {};
  if (Number.isFinite(min) && Number.isFinite(max)) parts.range = `${min}~${max}${unit}`;
  if (Number.isFinite(initial)) parts.initial = `초기 ${initial}`;
  if (perTurnDelta !== null && Number.isFinite(perTurnDelta)) {
    parts.perTurn = `턴당 ${perTurnDelta > 0 ? "+" : ""}${perTurnDelta}`;
  }
  const limit = [
    changeDirection === "both" ? undefined : STAT_CHANGE_DIRECTION_LABELS[changeDirection],
    maxChangePerTurn !== null && Number.isFinite(maxChangePerTurn) ? `최대 ${maxChangePerTurn}` : undefined,
  ].filter((part) => part !== undefined);
  if (limit.length > 0) parts.limit = limit.join(" · ");
  return parts;
}
