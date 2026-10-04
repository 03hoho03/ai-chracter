import { describe, expect, it } from "vitest";

import { statSummaryParts } from "./statSummary";

const base = {
  min: 0,
  max: 20,
  initial: 20,
  unit: "",
  perTurnDelta: null,
  changeDirection: "both",
  maxChangePerTurn: null,
} as const;

describe("statSummaryParts", () => {
  it("단위가 있으면 범위에 붙인다(초기값에는 반복하지 않는다)", () => {
    expect(statSummaryParts({ ...base, unit: "일" })).toEqual({ range: "0~20일", initial: "초기 20" });
  });

  it("단위가 비었거나 공백뿐이면 숫자만", () => {
    expect(statSummaryParts({ ...base, unit: "  " }).range).toBe("0~20");
    expect(statSummaryParts({ ...base, unit: undefined }).range).toBe("0~20");
  });

  it("턴당 변화는 부호를 붙인다", () => {
    expect(statSummaryParts({ ...base, perTurnDelta: -1 }).perTurn).toBe("턴당 -1");
    expect(statSummaryParts({ ...base, perTurnDelta: 2 }).perTurn).toBe("턴당 +2");
  });

  it("빈 숫자 칸(NaN)의 조각은 뺀다", () => {
    expect(statSummaryParts({ ...base, max: Number.NaN, initial: Number.NaN, perTurnDelta: Number.NaN })).toEqual({});
  });

  it("변화 제한은 오르내림이 아닌 방향과 최대 폭을 이어 한 조각으로 둔다(폭에는 단위를 붙이지 않는다)", () => {
    expect(statSummaryParts({ ...base, unit: "일", changeDirection: "decrease", maxChangePerTurn: 7 }).limit).toBe(
      "내리기만 · 최대 7",
    );
    expect(statSummaryParts({ ...base, changeDirection: "increase" }).limit).toBe("오르기만");
    expect(statSummaryParts({ ...base, maxChangePerTurn: 3 }).limit).toBe("최대 3");
  });

  it("오르내림·제한 없음·읽지 못한 폭 칸은 변화 제한 조각을 만들지 않는다", () => {
    expect(statSummaryParts(base).limit).toBeUndefined();
    expect(statSummaryParts({ ...base, maxChangePerTurn: Number.NaN }).limit).toBeUndefined();
  });
});
