import { describe, expect, it } from "vitest";

import { formatStatRuleDelta, statChangeMode, statRuleDeltaFromInput, statRuleDeltaHint } from "./statChange";

const rule = { id: "r1", condition: "사용자가 약속을 지켰다", delta: 3 };

describe("statChangeMode", () => {
  it("둘 다 비었으면 어느 쪽도 잠그지 않는다", () => {
    expect(statChangeMode({ perTurnDelta: null, rules: [] })).toBe("free");
  });

  it("턴당 자동 변화가 있으면 규칙 쪽을 잠근다", () => {
    expect(statChangeMode({ perTurnDelta: -1, rules: [] })).toBe("perTurn");
  });

  it("규칙이 하나라도 있으면 턴당 쪽을 잠근다(쓰다 만 규칙도 규칙이다)", () => {
    expect(statChangeMode({ perTurnDelta: null, rules: [rule] })).toBe("rules");
    expect(statChangeMode({ perTurnDelta: null, rules: [{ ...rule, condition: "", delta: Number.NaN }] })).toBe("rules");
  });

  it("둘 다 채워진 채 들어온 값은 어느 쪽도 잠그지 않는 충돌 상태다", () => {
    expect(statChangeMode({ perTurnDelta: -1, rules: [rule] })).toBe("conflict");
  });

  it("다 지우지 못한 턴당 칸(NaN)은 값으로 보지 않는다", () => {
    expect(statChangeMode({ perTurnDelta: Number.NaN, rules: [] })).toBe("free");
  });
});

describe("statRuleDeltaFromInput", () => {
  it("부호를 붙이거나 빼고 쓴 정수를 읽는다", () => {
    expect(statRuleDeltaFromInput("+3")).toBe(3);
    expect(statRuleDeltaFromInput("-5")).toBe(-5);
    expect(statRuleDeltaFromInput("7")).toBe(7);
    expect(statRuleDeltaFromInput(" -2 ")).toBe(-2);
  });

  it("수학 기호 빼기와 전각 부호도 받는다", () => {
    expect(statRuleDeltaFromInput("−4")).toBe(-4);
    expect(statRuleDeltaFromInput("＋2")).toBe(2);
  });

  it("빈 칸·부호만·소수·글자는 NaN 이다(0 은 숫자로 두고 검증이 막는다)", () => {
    for (const text of ["", "+", "-", "1.5", "3a", "+-3", "1e2"]) expect(statRuleDeltaFromInput(text)).toBeNaN();
    expect(statRuleDeltaFromInput("0")).toBe(0);
  });
});

describe("formatStatRuleDelta", () => {
  it("양수에도 부호를 붙이고 NaN 은 빈 칸으로 둔다", () => {
    expect(formatStatRuleDelta(3)).toBe("+3");
    expect(formatStatRuleDelta(-5)).toBe("-5");
    expect(formatStatRuleDelta(Number.NaN)).toBe("");
  });
});

describe("statRuleDeltaHint", () => {
  const range = { min: 0, max: 46 };

  it("빈 칸과 맞는 값에는 안내가 없다", () => {
    expect(statRuleDeltaHint("", Number.NaN, range)).toBeUndefined();
    expect(statRuleDeltaHint("-7", -7, range)).toBeUndefined();
    expect(statRuleDeltaHint("+46", 46, range)).toBeUndefined();
  });

  it("읽지 못한 글·0·범위 폭을 넘는 폭을 알린다", () => {
    expect(statRuleDeltaHint("3점", Number.NaN, range)).toContain("부호와 정수");
    expect(statRuleDeltaHint("0", 0, range)).toContain("0이 아닌");
    expect(statRuleDeltaHint("-47", -47, range)).toContain("범위 폭(46)");
  });

  it("범위가 아직 맞지 않으면 폭 경고를 하지 않는다", () => {
    expect(statRuleDeltaHint("+50", 50, { min: 0, max: Number.NaN })).toBeUndefined();
    expect(statRuleDeltaHint("+50", 50, { min: 10, max: 5 })).toBeUndefined();
  });
});
