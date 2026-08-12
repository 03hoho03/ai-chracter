import { describe, expect, it } from "vitest";

import { shouldShowSuggestedReplies } from "./shouldShowSuggestedReplies";

describe("shouldShowSuggestedReplies", () => {
  it("returns true when turnCount is 0 and replies exist", () => {
    expect(shouldShowSuggestedReplies(["주변을 둘러본다"], 0)).toBe(true);
  });

  it("returns false when turnCount is 1 or more even if replies exist", () => {
    expect(shouldShowSuggestedReplies(["주변을 둘러본다"], 1)).toBe(false);
    expect(shouldShowSuggestedReplies(["주변을 둘러본다"], 20)).toBe(false);
  });

  it("returns false when there are no replies even at turnCount 0", () => {
    expect(shouldShowSuggestedReplies([], 0)).toBe(false);
  });
});
