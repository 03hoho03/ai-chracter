import { describe, expect, it } from "vitest";

import type { NovelChapterSummary } from "@/entities/novel";

import { withChapterReadingPosition } from "./readingPositionCache";

type Chapter = Pick<NovelChapterSummary, "id" | "finishedReading" | "readingPosition"> & { title: string };

const position = { paragraphIndex: 7, paragraphCount: 20, revisionId: "r1", finished: false };

function detail(finishedReading = false): { chapters: Chapter[] } {
  return {
    chapters: [
      { id: "c3", finishedReading, readingPosition: null, title: "셋" },
      { id: "c4", finishedReading: false, readingPosition: null, title: "넷" },
    ],
  };
}

describe("withChapterReadingPosition", () => {
  it("떠나는 화의 자리를 상세 캐시의 그 화에만 먼저 써 둔다(돌아오면 그 자리로 연다)", () => {
    const next = withChapterReadingPosition(detail(), "c3", position);
    expect(next?.chapters[0]).toEqual({ id: "c3", finishedReading: false, readingPosition: position, title: "셋" });
    expect(next?.chapters[1]?.readingPosition).toBeNull();
  });

  it("다 읽음은 한 번 참이면 앞부분을 다시 읽어도 참이다(서버 규칙과 같다)", () => {
    const next = withChapterReadingPosition(detail(true), "c3", position);
    expect(next?.chapters[0]?.finishedReading).toBe(true);
    expect(next?.chapters[0]?.readingPosition?.finished).toBe(true);
  });

  it("상세가 없거나 그 화가 없으면 그대로다", () => {
    expect(withChapterReadingPosition(undefined, "c3", position)).toBeUndefined();
    const original = detail();
    expect(withChapterReadingPosition(original, "gone", position)).toBe(original);
  });
});
