import { describe, expect, it } from "vitest";

import type { WebnovelDetailResponse } from "../api/useWebnovelQuery";

import { withWebnovelReadingPosition } from "./webnovelReadingPositionCache";

function detail(finished: boolean): WebnovelDetailResponse {
  return {
    id: "n",
    title: "t",
    synopsis: "",
    source: { contentId: "c", contentType: "story", title: "s", characterName: null, coverUrl: null, linkable: true },
    publisherUserId: "p",
    publisherNickname: null,
    isPublisher: false,
    chapters: [
      {
        id: "a",
        ordinal: 1,
        title: null,
        access: "free",
        price: null,
        readingPosition: { paragraphIndex: 1, paragraphCount: 10, edition: 1, finished },
      },
      { id: "b", ordinal: 2, title: null, access: "free", price: null, readingPosition: null },
    ],
    freeChapterCount: 5,
    chapterPrice: 30,
    likeCount: 0,
    liked: false,
    viewCount: 0,
    lastRead: null,
    firstPublishedAt: "2026-10-09T00:00:00Z",
    publishedAt: "2026-10-09T00:00:00Z",
  };
}

describe("withWebnovelReadingPosition", () => {
  it("writes the last position into that chapter only", () => {
    const next = withWebnovelReadingPosition(detail(false), "b", {
      paragraphIndex: 4,
      paragraphCount: 9,
      edition: 2,
      finished: false,
    });
    expect(next?.chapters[1]?.readingPosition).toEqual({ paragraphIndex: 4, paragraphCount: 9, edition: 2, finished: false });
    expect(next?.chapters[0]?.readingPosition?.paragraphIndex).toBe(1);
  });

  it("keeps a chapter finished once it was finished", () => {
    const next = withWebnovelReadingPosition(detail(true), "a", { paragraphIndex: 0, paragraphCount: 10, edition: 1, finished: false });
    expect(next?.chapters[0]?.readingPosition?.finished).toBe(true);
  });

  it("returns the cache untouched when the chapter is not in it", () => {
    const original = detail(false);
    expect(withWebnovelReadingPosition(original, "z", { paragraphIndex: 0, paragraphCount: 1, edition: 1, finished: false })).toBe(
      original,
    );
    expect(withWebnovelReadingPosition(undefined, "a", { paragraphIndex: 0, paragraphCount: 1, edition: 1, finished: false })).toBeUndefined();
  });
});
