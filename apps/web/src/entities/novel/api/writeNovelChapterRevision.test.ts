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
      scenes: [],
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

  it("글이 그대로인 수정안을 적용한 응답이면 적용한 수정안만 뺀다", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(novelKeys.detail(NOVEL_ID), {
      id: NOVEL_ID,
      chapters: [{ id: CHAPTER_ID, currentRevisionId: "r1" }],
      pendingAiEdits: [
        { id: "edit-applied", chapterId: CHAPTER_ID },
        { id: "edit-here", chapterId: CHAPTER_ID },
      ],
    });
    queryClient.setQueryData(novelKeys.chapter(NOVEL_ID, CHAPTER_ID, "r1"), chapterAt("r1", ["하나", "둘"], "generate"));
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "둘"], "ai_edit"), { appliedEditId: "edit-applied" });
    expect(pendingIds(queryClient)).toEqual(["edit-here"]);
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

describe("writeNovelChapterRevision — 여러 문단 수정안", () => {
  function patch(id: string, blockId: string) {
    return { id, blockId, state: "pending", paragraphs: [`${id} 수정안`], fresh: true };
  }

  /** 지금 판 `r1` 의 그 화에 여러 문단 수정 작업 둘(j1: p1·p2, j2: p3)이 있는 캐시. */
  function seedBlockEdits() {
    const queryClient = seed(["하나", "둘"]);
    const detail = queryClient.getQueryData<object>(novelKeys.detail(NOVEL_ID));
    queryClient.setQueryData(novelKeys.detail(NOVEL_ID), {
      ...detail,
      pendingBlockEdits: [
        { id: "j1", chapterId: CHAPTER_ID, instruction: "짧게", patches: [patch("p1", "block-0"), patch("p2", "block-1")], bundles: [] },
        { id: "j2", chapterId: CHAPTER_ID, instruction: "길게", patches: [patch("p3", "block-1")], bundles: [] },
      ],
    });
    return queryClient;
  }

  function patchStates(queryClient: QueryClient) {
    return queryClient
      .getQueryData<{ pendingBlockEdits: { id: string; patches: { id: string; state: string }[] }[] }>(novelKeys.detail(NOVEL_ID))
      ?.pendingBlockEdits.map((edit) => [edit.id, edit.patches.map((item) => `${item.id}:${item.state}`)]);
  }

  // 서버는 블록 단위로 낡음을 판정한다 — 글이 바뀐 판이어도 다른 블록의 수정안은 살아 있다. 화 단위로 빼면 다시 받을 때 되살아나 깜빡인다.
  it("글이 바뀐 판이어도 여러 문단 수정안은 빼지 않는다", () => {
    const queryClient = seedBlockEdits();
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "둘 고침"], "manual_edit"));
    expect(patchStates(queryClient)).toEqual([
      ["j1", ["p1:pending", "p2:pending"]],
      ["j2", ["p3:pending"]],
    ]);
  });

  it("단위를 적용한 응답이면 그 수정안만 적용으로 바꾸고 옛 수정안 규칙은 그대로 쓴다", () => {
    const queryClient = seedBlockEdits();
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나 고침", "둘"], "ai_edit"), {
      appliedPatches: { jobId: "j1", patchIds: ["p1"] },
    });
    expect(patchStates(queryClient)).toEqual([
      ["j1", ["p1:applied", "p2:pending"]],
      ["j2", ["p3:pending"]],
    ]);
    // 글이 바뀌었으니 옛 연속 범위 수정안은 그 화에서 빠진다(서버와 같은 규칙).
    expect(pendingIds(queryClient)).toEqual(["edit-other"]);
  });

  it("마지막 대기 수정안을 적용한 작업은 목록에서 빠진다", () => {
    const queryClient = seedBlockEdits();
    writeNovelChapterRevision(queryClient, chapterAt("r2", ["하나", "셋"], "ai_edit"), {
      appliedPatches: { jobId: "j2", patchIds: ["p3"] },
    });
    expect(patchStates(queryClient)?.map(([id]) => id)).toEqual(["j1"]);
  });
});
