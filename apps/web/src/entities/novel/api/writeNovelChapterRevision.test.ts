import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { novelKeys } from "./keys";
import type { NovelChapterResponse } from "./useNovelChapterQuery";
import { writeNovelChapterRevision } from "./writeNovelChapterRevision";

const NOVEL_ID = "novel-1";
const CHAPTER_ID = "chapter-1";

function chapterAt(revisionId: string, paragraphs: string[], source: NovelChapterResponse["revision"]["source"]) {
  return {
    id: CHAPTER_ID,
    novelId: NOVEL_ID,
    ordinal: 1,
    assistantMessageCount: 4,
    revision: {
      id: revisionId,
      revisionNo: 2,
      source,
      revertedFromRevisionId: null,
      createdAt: "2026-10-23T00:00:00Z",
      body: paragraphs.join("\n\n"),
      paragraphs,
      blocks: paragraphs.map((_, index) => ({ id: `block-${index}`, text: paragraphs[index] ?? "" })),
      illustrations: [],
      unplacedIllustrations: [],
    },
  } satisfies NovelChapterResponse;
}

/** 지금 판이 `r1`(글 `paragraphs`)이고 그 화에 적용하지 않은 수정안 하나, 다른 화에 하나가 있는 캐시. 지금 판 본문 캐시는
 * `hasCurrentChapter` 일 때만 둔다. */
function seed(paragraphs: string[], { hasCurrentChapter = true } = {}) {
  const queryClient = new QueryClient();
  queryClient.setQueryData(novelKeys.detail(NOVEL_ID), {
    id: NOVEL_ID,
    chapters: [{ id: CHAPTER_ID, currentRevisionId: "r1" }],
    pendingAiEdits: [
      { id: "edit-here", chapterId: CHAPTER_ID },
      { id: "edit-other", chapterId: "chapter-2" },
    ],
  });
  if (hasCurrentChapter) queryClient.setQueryData(novelKeys.chapter(NOVEL_ID, CHAPTER_ID, "r1"), chapterAt("r1", paragraphs, "generate"));
  return queryClient;
}

function pendingIds(queryClient: QueryClient): string[] | undefined {
  return queryClient
    .getQueryData<{ pendingAiEdits: { id: string }[] }>(novelKeys.detail(NOVEL_ID))
    ?.pendingAiEdits.map((edit) => edit.id);
}

describe("writeNovelChapterRevision", () => {
  it("새 판의 글이 직전 판 글과 같으면(삽화만 바꾼 판·같은 글 판으로 되돌림) 그 화의 수정안을 남긴다", () => {
    const queryClient = seed(["하나", "둘"]);
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "둘"], "illustration"));
    expect(pendingIds(queryClient)).toEqual(["edit-here", "edit-other"]);
  });

  it("글이 바뀐 새 판이면 그 화의 수정안만 뺀다", () => {
    const queryClient = seed(["하나", "둘"]);
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "둘 고침"], "manual_edit"));
    expect(pendingIds(queryClient)).toEqual(["edit-other"]);
  });

  it("직전 판 본문을 캐시에 갖고 있지 않으면 그 화의 수정안을 뺀다", () => {
    const queryClient = seed(["하나", "둘"], { hasCurrentChapter: false });
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "둘"], "illustration"));
    expect(pendingIds(queryClient)).toEqual(["edit-other"]);
  });

  it("상세의 현재 판을 새 판으로 고치고 새 판 본문을 그 키에 쓴다", () => {
    const queryClient = seed(["하나", "둘"]);
    const next = chapterAt("r2", ["하나", "둘"], "illustration");
    writeNovelChapterRevision(queryClient, next);
    expect(queryClient.getQueryData(novelKeys.chapter(NOVEL_ID, CHAPTER_ID, "r2"))).toEqual(next);
    expect(
      queryClient.getQueryData<{ chapters: { currentRevisionId: string }[] }>(novelKeys.detail(NOVEL_ID))?.chapters[0]
        ?.currentRevisionId,
    ).toBe("r2");
  });
});
