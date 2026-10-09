import { describe, expect, it } from "vitest";

import { isGlobalHeaderHidden } from "./isGlobalHeaderHidden";

describe("isGlobalHeaderHidden", () => {
  it.each(["/builder", "/builder/character/draft-1", "/novels/a/episodes/b", "/novels/a/board"])(
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
    "/chat/room-1",
    "/studio/images",
  ])("keeps the global header on %s", (pathname) => {
    expect(isGlobalHeaderHidden(pathname)).toBe(false);
  });
});
