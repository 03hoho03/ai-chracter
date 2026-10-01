import { describe, expect, it } from "vitest";

import { countCommentGraphemes, uniqueComments } from "./commentText";

describe("comment text and overlapping pages", () => {
  it("counts composed Hangul, family, skin tone and flags as visible characters", () => {
    expect(countCommentGraphemes("가👨‍👩‍👧‍👦👍🏽🇰🇷")).toBe(4);
    expect(countCommentGraphemes("👍🏽".repeat(1000))).toBe(1000);
    expect(countCommentGraphemes("👍🏽".repeat(1001))).toBe(1001);
  });
  it("keeps one row and the latest payload across overlapping cursor pages", () => {
    expect(uniqueComments([{ id: "a", likes: 2 }, { id: "b", likes: 1 }, { id: "a", likes: 3 }]))
      .toEqual([{ id: "a", likes: 3 }, { id: "b", likes: 1 }]);
  });
});
