import { describe, expect, it } from "vitest";

import { isSiteFooterHidden } from "./isSiteFooterHidden";

describe("isSiteFooterHidden", () => {
  it.each(["/chat/room-1", "/builder", "/builder/character/draft-1", "/studio/images", "/studio/images/anything"])(
    "hides the footer on the viewport-filling screen %s",
    (pathname) => {
      expect(isSiteFooterHidden(pathname)).toBe(true);
    },
  );

  it.each(["/", "/chats", "/builderx", "/studio", "/studio/imagesx", "/content/character/1", "/about", "/chat"])(
    "keeps the footer on the document-scrolling screen %s",
    (pathname) => {
      expect(isSiteFooterHidden(pathname)).toBe(false);
    },
  );

  it("hides the footer on the immersive novel episode viewer", () => {
    expect(isSiteFooterHidden("/novels/a/episodes/b")).toBe(true);
  });

  it("hides the footer on the immersive webnovel episode viewer", () => {
    expect(isSiteFooterHidden("/webnovels/a/episodes/b")).toBe(true);
  });

  it("hides the footer on the viewport-filling novel edit board", () => {
    expect(isSiteFooterHidden("/novels/a/board")).toBe(true);
  });

  it.each([
    "/novels",
    "/novels/a",
    "/novels/a/episodes",
    "/novels/a/episodes/b/extra",
    "/novels/a/boardx",
    "/novels/a/board/extra",
    "/webnovels",
    "/webnovels/a",
    "/webnovels/a/board",
  ])(
    "keeps the footer on the novel document screen %s",
    (pathname) => {
      expect(isSiteFooterHidden(pathname)).toBe(false);
    },
  );
});
