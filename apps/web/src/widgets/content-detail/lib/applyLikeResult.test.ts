import { describe, expect, it } from "vitest";

import { applyLikeResult } from "./applyLikeResult";

describe("applyLikeResult", () => {
  it("leaves an empty cache empty", () => {
    expect(applyLikeResult(undefined, true)).toBeUndefined();
  });

  it("adds one to the count when a like lands on an unliked entry", () => {
    expect(applyLikeResult({ id: "a", isLiked: false, likeCount: 3 }, true)).toEqual({ id: "a", isLiked: true, likeCount: 4 });
  });

  it("subtracts one from the count when an unlike lands on a liked entry", () => {
    expect(applyLikeResult({ id: "a", isLiked: true, likeCount: 3 }, false)).toEqual({ id: "a", isLiked: false, likeCount: 2 });
  });

  it.each([true, false])("keeps the count when the entry already holds %s, so a refetch that won the race is not counted twice", (isLiked) => {
    expect(applyLikeResult({ id: "a", isLiked, likeCount: 3 }, isLiked)).toEqual({ id: "a", isLiked, likeCount: 3 });
  });
});
