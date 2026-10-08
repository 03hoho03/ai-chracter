import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "../api/useNovelQuery";

import { isChapterRegenerating } from "./chapterRegenerationLock";

const CHAPTER = "chapter-1";
const BATCH = "batch-1";

function job(overrides: Partial<NonNullable<NovelDetailResponse["activeJob"]>>): NovelDetailResponse["activeJob"] {
  return {
    id: "j",
    kind: "chapter_regenerate",
    status: "running",
    chapterId: null,
    batchId: BATCH,
    completedBatches: null,
    plannedBatches: null,
    ...overrides,
  };
}

describe("isChapterRegenerating", () => {
  it("진행 중 작업이 없으면 잠그지 않는다", () => {
    expect(isChapterRegenerating(null, CHAPTER, BATCH)).toBe(false);
  });

  // 묶음 다시 만들기는 고른 화 하나가 아니라 같은 묶음의 화 전부에 새 판을 쌓는다.
  it("이 화가 든 묶음을 다시 만드는 중이면 고른 화가 아니어도 잠근다", () => {
    expect(isChapterRegenerating(job({ chapterId: "chapter-2" }), CHAPTER, BATCH)).toBe(true);
    expect(isChapterRegenerating(job({ status: "queued" }), CHAPTER, BATCH)).toBe(true);
  });

  // 다른 묶음의 재생성 결과는 이 화에 판을 쌓지 않는다 — 이 화에서 저장한 글이 밀려나지 않는다.
  it("다른 묶음을 다시 만드는 중이면 잠그지 않는다", () => {
    expect(isChapterRegenerating(job({ batchId: "batch-2", chapterId: CHAPTER }), CHAPTER, BATCH)).toBe(false);
  });

  it("묶음이 없는 옛 작업은 가리키는 화로 판단한다", () => {
    expect(isChapterRegenerating(job({ batchId: null, chapterId: CHAPTER }), CHAPTER, BATCH)).toBe(true);
    expect(isChapterRegenerating(job({ batchId: null, chapterId: "chapter-2" }), CHAPTER, BATCH)).toBe(false);
  });

  // 새 화 만들기·연쇄는 새 화를 쌓고, AI 수정은 적용 전까지 본문을 바꾸지 않는다.
  it.each(["chapter_generate", "chain_generate", "ai_edit"] as const)("%s 는 잠그지 않는다", (kind) => {
    expect(isChapterRegenerating(job({ kind, chapterId: CHAPTER }), CHAPTER, BATCH)).toBe(false);
  });
});
