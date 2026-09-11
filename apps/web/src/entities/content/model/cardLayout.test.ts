import { describe, expect, it } from "vitest";

import { toGridColumns, toThumbnailAspect } from "./cardLayout";

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

  it("portrait만 lg 단계(5열)를 갖는다 — 390px 3열은 작가명 공간 부족으로 기각(D-5)", () => {
    expect(toGridColumns("portrait")).toBe("grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5");
  });

  it("mixed는 square와 같은 열 수에 items-start를 더한다", () => {
    expect(toGridColumns("mixed")).toBe("grid-cols-2 sm:grid-cols-3 md:grid-cols-4 items-start");
  });
});
