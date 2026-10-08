import { describe, expect, it } from "vitest";

import { statSummaryParts } from "./statSummary";

const base = {
  min: 0,
  max: 20,
  initial: 20,
  unit: "",
  perTurnDelta: null,
  rules: [],
};

const rule = { id: "r1", condition: "사용자가 약속을 지켰다", delta: 3 };

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

  it("규칙이 있으면 그 수를, 없으면 조각을 만들지 않는다", () => {
    expect(statSummaryParts({ ...base, rules: [rule, { ...rule, id: "r2" }] }).rules).toBe("규칙 2개");
    expect(statSummaryParts(base).rules).toBeUndefined();
  });
});
