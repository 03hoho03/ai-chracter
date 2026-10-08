import { describe, expect, it } from "vitest";

import { easeOut } from "./pageTransition";

describe("easeOut", () => {
  it("시작은 0, 끝은 1 이고 범위 밖 입력은 양 끝에 붙는다", () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(-0.5)).toBe(0);
    expect(easeOut(1.5)).toBe(1);
  });

  it("앞에서 빠르고 뒤에서 느려진다 — 시간 절반에 거리의 절반보다 멀리 가 있다", () => {
    expect(easeOut(0.5)).toBeGreaterThan(0.75);
    expect(easeOut(0.5)).toBeLessThan(0.85);
  });

  it("cubic-bezier(0, 0, 0.2, 1) 의 알려진 점을 지난다", () => {
    // s = 0.5 에서 x = 0.2, y = 0.5.
    expect(easeOut(0.2)).toBeCloseTo(0.5, 4);
  });

  it("시간이 가면 줄어들지 않는다", () => {
    let previous = 0;
    for (let index = 1; index <= 100; index += 1) {
      const value = easeOut(index / 100);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });
});
