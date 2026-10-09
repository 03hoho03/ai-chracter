import { describe, expect, it } from "vitest";

import { canReportComposingValue } from "./clampFieldAtCaret";

describe("canReportComposingValue", () => {
  it("reports a composing value that still fits, including one exactly at the limit", () => {
    expect(canReportComposingValue("가나", 3)).toBe(true);
    expect(canReportComposingValue("가나ㅎ", 3)).toBe(true);
  });

  it("holds back a composing value past the limit so autosave never sends it", () => {
    expect(canReportComposingValue("가나다ㅎ", 3)).toBe(false);
  });

  it("counts code points, so an emoji does not count twice", () => {
    expect(canReportComposingValue("😀😀ㅎ", 3)).toBe(true);
  });
});
