import { describe, expect, it } from "vitest";

import { getResultTileLayout, parseAspectRatio, RESULT_TILE_MAX_HEIGHT_PX } from "./resultTileLayout";

describe("parseAspectRatio", () => {
  it("가로 비율은 앞 숫자가 폭, 뒤 숫자가 높이다", () => {
    expect(parseAspectRatio("16:9")).toEqual({ width: 16, height: 9 });
  });

  it("세로 비율은 폭과 높이가 뒤바뀌지 않는다", () => {
    expect(parseAspectRatio("9:16")).toEqual({ width: 9, height: 16 });
  });
});

describe("getResultTileLayout", () => {
  it("높이 상한은 320px이다", () => {
    expect(RESULT_TILE_MAX_HEIGHT_PX).toBe(320);
  });

  it("세로 3:4 두 장이면 두 열이고, 열 폭은 높이가 320에 닿는 240px에서 멈춘다", () => {
    expect(getResultTileLayout("3:4", 2)).toEqual({
      gridTemplateColumns: "repeat(2, minmax(0, 240px))",
      aspectRatio: "3 / 4",
    });
  });

  it("정사각 두 장이면 열 폭 상한이 320px이다", () => {
    expect(getResultTileLayout("1:1", 2).gridTemplateColumns).toBe("repeat(2, minmax(0, 320px))");
  });

  it("가로 16:9 한 장이면 한 열이고, 열 폭 상한은 반올림한 569px이다", () => {
    expect(getResultTileLayout("16:9", 1)).toEqual({
      gridTemplateColumns: "repeat(1, minmax(0, 569px))",
      aspectRatio: "16 / 9",
    });
  });

  it("세로 9:16 한 장이면 열 폭 상한이 180px이다", () => {
    expect(getResultTileLayout("9:16", 1).gridTemplateColumns).toBe("repeat(1, minmax(0, 180px))");
  });

  it("2:3 한 장이면 열 폭 상한이 213px이다", () => {
    expect(getResultTileLayout("2:3", 1).gridTemplateColumns).toBe("repeat(1, minmax(0, 213px))");
  });
});
