import { describe, expect, it } from "vitest";

import { mediaImageFrameStyle } from "./MediaImageFrame";

// 원본 비율 그림은 높이가 상한(320px)에 닿는 폭으로 틀을 못박고 컬럼 폭으로만 줄인다 — 그림이 오기 전에 높이가 정해진다.
describe("mediaImageFrameStyle", () => {
  it.each([
    ["portrait 3:4", 768, 1024, "240px"],
    ["square", 512, 512, "320px"],
    ["landscape 16:9", 1920, 1080, "569px"],
  ])("caps a %s image at the well height", (_name, width, height, expectedWidth) => {
    expect(mediaImageFrameStyle(width, height)).toEqual({
      aspectRatio: `${width} / ${height}`,
      width: expectedWidth,
      maxWidth: "100%",
    });
  });

  it.each([
    [undefined, 1024],
    [768, undefined],
    [0, 1024],
    [768, -1],
  ])("falls back to the fixed well when the size is unknown (%s × %s)", (width, height) => {
    expect(mediaImageFrameStyle(width, height)).toBeUndefined();
  });
});
