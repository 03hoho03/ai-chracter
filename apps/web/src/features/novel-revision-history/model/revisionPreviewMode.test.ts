import { describe, expect, it } from "vitest";

import { toInitialPreviewMode } from "./revisionPreviewMode";

describe("toInitialPreviewMode", () => {
  it("앞 판이 있으면 그 판이 바꾼 곳부터 보인다", () => {
    expect(toInitialPreviewMode({ source: "manual_edit", hasPrevious: true, hasCurrent: true })).toBe("previous");
    expect(toInitialPreviewMode({ source: "manual_edit", hasPrevious: true, hasCurrent: false })).toBe("previous");
  });

  it("첫 판이면 지금 글과 비교한다", () => {
    expect(toInitialPreviewMode({ source: "manual_edit", hasPrevious: false, hasCurrent: true })).toBe("current");
  });

  it("판이 하나뿐이면 글 그대로", () => {
    expect(toInitialPreviewMode({ source: "manual_edit", hasPrevious: false, hasCurrent: false })).toBe("text");
  });

  it("삽화를 바꾼 판은 글이 앞 판과 같아 비교가 할 말이 없다 — 그 판 글(그림 포함)부터 보인다", () => {
    expect(toInitialPreviewMode({ source: "illustration", hasPrevious: true, hasCurrent: true })).toBe("text");
    expect(toInitialPreviewMode({ source: "illustration", hasPrevious: true, hasCurrent: false })).toBe("text");
  });

  it("삽화 밖의 출처는 지금처럼 고른다", () => {
    for (const source of ["generate", "regenerate", "manual_edit", "ai_edit", "revert"] as const) {
      expect(toInitialPreviewMode({ source, hasPrevious: true, hasCurrent: true })).toBe("previous");
    }
  });
});
