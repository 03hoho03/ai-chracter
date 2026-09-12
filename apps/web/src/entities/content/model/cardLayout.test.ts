import { describe, expect, it } from "vitest";

import { toThumbnailAspect } from "./cardLayout";
import { toGridColumns } from "../ui/cardLayoutClass";

describe("toThumbnailAspect", () => {
  it("character -> square", () => {
    expect(toThumbnailAspect("character")).toBe("square");
  });

  it("story -> portrait", () => {
    expect(toThumbnailAspect("story")).toBe("portrait");
  });
});

describe("toGridColumns", () => {
  it("square는 md에서 멈춘다(2/3/4)", () => {
    expect(toGridColumns("square")).toBe("grid-cols-2 sm:grid-cols-3 md:grid-cols-4");
  });

  it("portrait은 390px부터 3열이다 — 카드 껍데기가 걷혀 작가명 공간 부족 근거가 사라졌다(D-5 갱신)", () => {
    expect(toGridColumns("portrait")).toBe("grid-cols-3 sm:grid-cols-4 md:grid-cols-5");
  });

  it("mixed는 square와 같은 열 수에 items-start를 더한다", () => {
    expect(toGridColumns("mixed")).toBe("grid-cols-2 sm:grid-cols-3 md:grid-cols-4 items-start");
  });
});
