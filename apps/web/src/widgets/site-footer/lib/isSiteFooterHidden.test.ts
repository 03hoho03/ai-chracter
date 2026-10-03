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
});
