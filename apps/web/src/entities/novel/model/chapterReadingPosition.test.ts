import { describe, expect, it } from "vitest";

import { readChapterReadingPosition } from "./chapterReadingPosition";

const position = {
  paragraphIndex: 3,
  paragraphCount: 10,
  revisionId: "r1",
  finished: false,
  updatedAt: "2026-10-08T00:00:00Z",
};

describe("readChapterReadingPosition", () => {
  it("응답에 실린 자리를 그대로 돌려준다", () => {
    expect(readChapterReadingPosition({ readingPosition: position })).toBe(position);
  });

  it("읽은 적 없는 화는 null", () => {
    expect(readChapterReadingPosition({ readingPosition: null })).toBeNull();
  });

  it("칸이 없는 옛 응답은 undefined 로 가른다", () => {
    expect(readChapterReadingPosition({})).toBeUndefined();
  });
});
