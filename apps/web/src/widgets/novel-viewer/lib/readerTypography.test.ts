import { describe, expect, it } from "vitest";

import {
  DEFAULT_READER_SETTINGS,
  READER_FONT_SIZES,
  READER_LINE_HEIGHTS,
  READER_MARGINS,
  type ReaderSettings,
} from "../model/readerSettings";
import { readerTypographyClassName } from "./readerTypography";

describe("readerTypographyClassName", () => {
  it("단계 이름을 리터럴 Tailwind 클래스로 옮긴다", () => {
    // 넘김 방식·화면 유지는 글자 클래스와 무관해 기본값으로 채운다.
    const classNameOf = (settings: Pick<ReaderSettings, "fontSize" | "lineHeight" | "margin">) =>
      readerTypographyClassName({ ...DEFAULT_READER_SETTINGS, ...settings });

    expect(classNameOf({ fontSize: "small", lineHeight: "normal", margin: "narrow" })).toBe("text-sm leading-normal px-4");
    expect(classNameOf({ fontSize: "medium", lineHeight: "relaxed", margin: "medium" })).toBe(
      "text-lg leading-relaxed px-6",
    );
    expect(classNameOf({ fontSize: "large", lineHeight: "loose", margin: "wide" })).toBe("text-xl leading-loose px-8");
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
          const classes = readerTypographyClassName({ ...DEFAULT_READER_SETTINGS, fontSize, lineHeight, margin }).split(" ");

          expect(classes).toHaveLength(3);
          for (const name of classes) expect(allowed).toContain(name);
        }
      }
    }
  });
});
