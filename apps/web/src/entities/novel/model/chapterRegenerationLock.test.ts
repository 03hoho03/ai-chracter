import { describe, expect, it } from "vitest";

import { isChapterRegenerating } from "./chapterRegenerationLock";

const CHAPTER = "chapter-1";
const OTHER = "chapter-2";

describe("isChapterRegenerating", () => {
  it("진행 중 작업이 없으면 잠그지 않는다", () => {
    expect(isChapterRegenerating(null, CHAPTER)).toBe(false);
  });

  it("그 장을 다시 만드는 중이면 잠근다", () => {
    expect(isChapterRegenerating({ id: "j", kind: "chapter_regenerate", status: "running", chapterId: CHAPTER }, CHAPTER)).toBe(true);
    expect(isChapterRegenerating({ id: "j", kind: "chapter_regenerate", status: "queued", chapterId: CHAPTER }, CHAPTER)).toBe(true);
  });

  // 다른 장의 재생성 결과는 이 장에 판을 쌓지 않는다 — 이 장에서 저장한 글이 밀려나지 않는다.
  it("다른 장을 다시 만드는 중이면 잠그지 않는다", () => {
    expect(isChapterRegenerating({ id: "j", kind: "chapter_regenerate", status: "running", chapterId: OTHER }, CHAPTER)).toBe(false);
  });

  // 새 장 만들기는 새 장을 쌓고, AI 수정은 적용 전까지 본문을 바꾸지 않는다.
  it.each(["chapter_generate", "ai_edit"] as const)("%s 는 잠그지 않는다", (kind) => {
    expect(isChapterRegenerating({ id: "j", kind, status: "running", chapterId: CHAPTER }, CHAPTER)).toBe(false);
  });
});
