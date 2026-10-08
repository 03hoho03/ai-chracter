import { describe, expect, it } from "vitest";

import { toInitialPreviewMode } from "./revisionPreviewMode";

describe("toInitialPreviewMode", () => {
  it("앞 판이 있으면 그 판이 바꾼 곳부터 보인다", () => {
    expect(toInitialPreviewMode({ hasPrevious: true, hasCurrent: true })).toBe("previous");
    expect(toInitialPreviewMode({ hasPrevious: true, hasCurrent: false })).toBe("previous");
  });

  it("첫 판이면 지금 글과 비교한다", () => {
    expect(toInitialPreviewMode({ hasPrevious: false, hasCurrent: true })).toBe("current");
  });

  it("판이 하나뿐이면 글 그대로", () => {
    expect(toInitialPreviewMode({ hasPrevious: false, hasCurrent: false })).toBe("text");
  });
});
