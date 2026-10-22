import { describe, expect, it } from "vitest";

import { toCropAspect } from "./cropAspect";

describe("toCropAspect", () => {
  it("고정 비율 칩은 그 비율이다", () => {
    expect(toCropAspect({ label: "3:4", ratio: 3 / 4 }, { width: 1000, height: 500 })).toBe(0.75);
  });

  // 원본 칩은 그림 자체의 비율이라, 확대하지 않으면 그림 전체가 잘리지 않고 남는다.
  it("원본 칩은 그림의 가로 대 세로다", () => {
    expect(toCropAspect({ label: "원본", ratio: "original" }, { width: 1080, height: 2340 })).toBeCloseTo(1080 / 2340);
  });

  it("그림 크기를 아직 모르면 원본 칩의 비율도 아직 없다", () => {
    expect(toCropAspect({ label: "원본", ratio: "original" }, undefined)).toBeUndefined();
  });
});
