import { describe, expect, it } from "vitest";

import { toThumbnailAspect, toThumbnailAspectRatio } from "./cardLayout";
import { toGridColumns } from "../ui/cardLayoutClass";

describe("toThumbnailAspect", () => {
  it("character -> square", () => {
    expect(toThumbnailAspect("character")).toBe("square");
  });

  it("story -> portrait", () => {
    expect(toThumbnailAspect("story")).toBe("portrait");
  });
});

describe("toThumbnailAspectRatio", () => {
  it("square -> 1", () => {
    expect(toThumbnailAspectRatio("square")).toBe(1);
  });

  it("portrait -> 2/3", () => {
    expect(toThumbnailAspectRatio("portrait")).toBe(2 / 3);
  });
});

describe("toGridColumns", () => {
  // 경계는 뷰포트가 아니라 그리드 폭이다 — 37rem·45rem 은 뷰포트 sm·md 에서 거터 48px 를 뺀 폭이라, 패널이 없는
  // 화면은 지금까지와 같은 열이 나오고 왼쪽 패널이 폭을 가져간 화면은 카드가 받는 폭대로 열이 정해진다.
  it("square는 그리드 폭 37rem·45rem 에서 2/3/4열로 오른다", () => {
    expect(toGridColumns("square")).toBe("grid-cols-2 @min-[37rem]:grid-cols-3 @min-[45rem]:grid-cols-4");
  });

  it("portrait은 가장 좁은 폭부터 3열이다 — 카드 껍데기가 걷혀 작가명 공간 부족 근거가 사라졌다", () => {
    expect(toGridColumns("portrait")).toBe("grid-cols-3 @min-[37rem]:grid-cols-4 @min-[45rem]:grid-cols-5");
  });

  it("mixed는 square와 같은 열 수에 items-start를 더한다", () => {
    expect(toGridColumns("mixed")).toBe("grid-cols-2 @min-[37rem]:grid-cols-3 @min-[45rem]:grid-cols-4 items-start");
  });
});
