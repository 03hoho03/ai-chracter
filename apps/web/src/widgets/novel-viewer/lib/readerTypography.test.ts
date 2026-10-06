import { describe, expect, it } from "vitest";

import { READER_FONT_SIZES, READER_LINE_HEIGHTS, READER_MARGINS } from "../model/readerSettings";
import { readerTypographyClassName } from "./readerTypography";

describe("readerTypographyClassName", () => {
  it("단계 이름을 리터럴 Tailwind 클래스로 옮긴다", () => {
    expect(readerTypographyClassName({ fontSize: "small", lineHeight: "normal", margin: "narrow" })).toBe(
      "text-sm leading-normal px-4",
    );
    expect(readerTypographyClassName({ fontSize: "medium", lineHeight: "relaxed", margin: "medium" })).toBe(
      "text-lg leading-relaxed px-6",
    );
    expect(readerTypographyClassName({ fontSize: "large", lineHeight: "loose", margin: "wide" })).toBe(
      "text-xl leading-loose px-8",
    );
  });

  // 디자인 규칙: 글자 크기 천장은 text-2xl 이고, text-base 는 text-sm 과 같은 값이라 단계로 쓰지 않는다.
  it("모든 조합이 허용된 클래스만 낸다", () => {
    const allowed = [
      "text-sm",
      "text-lg",
      "text-xl",
      "leading-normal",
      "leading-relaxed",
      "leading-loose",
      "px-4",
      "px-6",
      "px-8",
    ];

    for (const fontSize of READER_FONT_SIZES) {
      for (const lineHeight of READER_LINE_HEIGHTS) {
        for (const margin of READER_MARGINS) {
          const classes = readerTypographyClassName({ fontSize, lineHeight, margin }).split(" ");

          expect(classes).toHaveLength(3);
          for (const name of classes) expect(allowed).toContain(name);
        }
      }
    }
  });
});
