import { describe, expect, it } from "vitest";

import {
  isBlockedMaxChangeKey,
  isBlockedMaxChangePaste,
  maxChangePerTurnFromInput,
  statChangeMode,
} from "./statChange";

const unset = { perTurnDelta: null, changeDirection: "both", maxChangePerTurn: null } as const;

describe("statChangeMode", () => {
  it("둘 다 비었으면 어느 쪽도 잠그지 않는다", () => {
    expect(statChangeMode(unset)).toBe("free");
  });

  it("턴당 자동 변화가 있으면 방향·폭 쪽을 잠근다", () => {
    expect(statChangeMode({ ...unset, perTurnDelta: -1 })).toBe("perTurn");
  });

  it("방향이 오르내림이 아니거나 폭이 차 있으면 턴당 쪽을 잠근다", () => {
    expect(statChangeMode({ ...unset, changeDirection: "decrease" })).toBe("limit");
    expect(statChangeMode({ ...unset, changeDirection: "increase" })).toBe("limit");
    expect(statChangeMode({ ...unset, maxChangePerTurn: 3 })).toBe("limit");
    // 읽지 못한 폭 칸도 비어 있지 않다 — 그 칸을 비우기 전에는 턴당 칸을 열지 않는다.
    expect(statChangeMode({ ...unset, maxChangePerTurn: Number.NaN })).toBe("limit");
  });

  it("둘 다 채워진 채 들어온 값은 어느 쪽도 잠그지 않는 충돌 상태다", () => {
    expect(statChangeMode({ perTurnDelta: -1, changeDirection: "decrease", maxChangePerTurn: 7 })).toBe("conflict");
  });

  it("다 지우지 못한 턴당 칸(NaN)은 값으로 보지 않는다", () => {
    expect(statChangeMode({ ...unset, perTurnDelta: Number.NaN })).toBe("free");
  });
});

describe("maxChangePerTurnFromInput", () => {
  it("빈 칸은 제한 없음(null)", () => {
    expect(maxChangePerTurnFromInput("")).toBeNull();
    expect(maxChangePerTurnFromInput(null)).toBeNull();
  });

  it("정수는 그대로 숫자로 둔다(0·음수는 폼 검증이 칸에 알린다)", () => {
    expect(maxChangePerTurnFromInput("7")).toBe(7);
    expect(maxChangePerTurnFromInput("0")).toBe(0);
    expect(maxChangePerTurnFromInput("-2")).toBe(-2);
  });

  it("정수가 아닌 값은 NaN 으로 둬 그대로 서버에 가지 않게 한다", () => {
    expect(maxChangePerTurnFromInput("1.5")).toBeNaN();
    expect(maxChangePerTurnFromInput("abc")).toBeNaN();
  });
});

describe("isBlockedMaxChangeKey", () => {
  it("음수·소수·지수 글자는 받지 않고 숫자와 편집 키는 받는다", () => {
    for (const key of ["-", "+", ".", ",", "e", "E"]) expect(isBlockedMaxChangeKey(key)).toBe(true);
    for (const key of ["0", "7", "Backspace", "ArrowUp", "Tab"]) expect(isBlockedMaxChangeKey(key)).toBe(false);
  });
});

describe("isBlockedMaxChangePaste", () => {
  it("숫자만으로 된 글은 받고 소수·음수·글자가 섞인 글은 막는다", () => {
    for (const text of ["7", "12"]) expect(isBlockedMaxChangePaste(text)).toBe(false);
    for (const text of ["2.5", "-1", "1e3", "abc", " 3", ""]) expect(isBlockedMaxChangePaste(text)).toBe(true);
  });
});
