import { describe, expect, it } from "vitest";

import { isGlobalHeaderHidden } from "./isGlobalHeaderHidden";

describe("isGlobalHeaderHidden", () => {
  it.each(["/builder", "/builder/character/draft-1", "/novels/a/episodes/b", "/novels/a/board", "/webnovels/a/episodes/b"])(
    "hides the global header on %s",
    (pathname) => {
      expect(isGlobalHeaderHidden(pathname)).toBe(true);
    },
  );

  it.each([
    "/",
    "/builderx",
    "/novels",
    "/novels/a",
    "/novels/a/episodes",
    "/novels/a/episodes/b/extra",
    "/novels/a/boardx",
    "/novels/a/board/extra",
    "/webnovels",
    "/webnovels/a",
    "/webnovels/a/episodes/b/extra",
    "/webnovels/a/board",
    "/xwebnovels/a/episodes/b",
    "/chat/room-1",
    "/studio/images",
  ])("keeps the global header on %s", (pathname) => {
    expect(isGlobalHeaderHidden(pathname)).toBe(false);
  });
});
