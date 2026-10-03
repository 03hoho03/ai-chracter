import { describe, expect, it } from "vitest";

import { exceedsClampLines } from "./clampedText";

describe("exceedsClampLines", () => {
  it("keeps short values whole", () => {
    expect(exceedsClampLines("유나와 대본을 맞추면 볼 수 있어요")).toBe(false);
    expect(exceedsClampLines("한 줄\n두 줄\n세 줄\n네 줄")).toBe(false);
  });

  it("counts explicit line breaks, blank lines included", () => {
    expect(exceedsClampLines("한 줄\n\n세 줄\n네 줄\n다섯 줄")).toBe(true);
  });

  it("counts wrapped lines of a long paragraph", () => {
    expect(exceedsClampLines("가".repeat(18 * 4))).toBe(false);
    expect(exceedsClampLines("가".repeat(18 * 4 + 1))).toBe(true);
  });
});
