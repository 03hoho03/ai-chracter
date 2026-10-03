import type { StatDefValues } from "@/features/build-story";

/** 접힌 스탯 머리 줄 요약의 글 조각. 비었거나 숫자가 아닌 칸의 조각은 없다. */
export type StatSummaryParts = {
  /** 범위와 단위(`0~20일`). 단위는 범위에만 붙인다 — 초기값은 같은 단위라 반복하면 줄만 길어진다. */
  range?: string;
  initial?: string;
  perTurn?: string;
};

export function statSummaryParts(stat: Pick<StatDefValues, "min" | "max" | "initial" | "unit" | "perTurnDelta">): StatSummaryParts {
  const { min, max, initial, perTurnDelta } = stat;
  const unit = stat.unit?.trim() ?? "";
  const parts: StatSummaryParts = {};
  if (Number.isFinite(min) && Number.isFinite(max)) parts.range = `${min}~${max}${unit}`;
  if (Number.isFinite(initial)) parts.initial = `초기 ${initial}`;
  if (perTurnDelta !== null && Number.isFinite(perTurnDelta)) {
    parts.perTurn = `턴당 ${perTurnDelta > 0 ? "+" : ""}${perTurnDelta}`;
  }
  return parts;
}
