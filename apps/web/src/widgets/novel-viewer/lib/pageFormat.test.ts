import { describe, expect, it } from "vitest";

import { READER_FONT_SIZES, READER_LINE_HEIGHTS } from "../model/readerSettings";
import { PAGE_TEXT_HEIGHT_PX, PAGE_TEXT_WIDTH_PX, toPageTypography } from "./pageFormat";

describe("판형", () => {
  it("360×540 판형에서 사방 여백 24 를 뺀 글 상자는 312×492 다", () => {
    expect([PAGE_TEXT_WIDTH_PX, PAGE_TEXT_HEIGHT_PX]).toEqual([312, 492]);
  });
});

describe("toPageTypography", () => {
  it("글자 크기는 16/18/20px, 줄 간격은 1.5/1.625/2 배다", () => {
    expect(toPageTypography({ fontSize: "small", lineHeight: "normal" })).toMatchObject({ fontSizePx: 16, lineHeight: 1.5 });
    expect(toPageTypography({ fontSize: "medium", lineHeight: "relaxed" })).toMatchObject({
      fontSizePx: 18,
      lineHeight: 1.625,
    });
    expect(toPageTypography({ fontSize: "large", lineHeight: "loose" })).toMatchObject({ fontSizePx: 20, lineHeight: 2 });
  });

  it("문단 간격은 줄 간격과 무관하게 글자 크기와 같다", () => {
    for (const fontSize of READER_FONT_SIZES) {
      for (const lineHeight of READER_LINE_HEIGHTS) {
        const typography = toPageTypography({ fontSize, lineHeight });

        expect(typography.paragraphGapPx).toBe(typography.fontSizePx);
      }
    }
  });
});
