import type { NovelChapterSummary } from "../api/useNovelQuery";

type ChapterKindFields = Pick<NovelChapterSummary, "batchId"> & Partial<Pick<NovelChapterSummary, "episodeOutlineId">>;

/** 구성안(장면 구성안)으로 쓴 화인가. 표지가 없는 응답의 화는 대화로 바로 만든 화다. */
export function isOutlineFlowChapter(chapter: Partial<Pick<NovelChapterSummary, "episodeOutlineId">>): boolean {
  return chapter.episodeOutlineId !== undefined && chapter.episodeOutlineId !== null;
}

/** 묶음이 구성안으로 쓴 화의 묶음인가 — 그 묶음의 화가 모두 구성안으로 쓴 화일 때다. 구성안으로 쓴 화는 화 하나짜리 묶음이라 "한 번에
 * 만든 화들"이라는 묶음의 뜻이 없어, 보드가 틀·머리를 그리지 않는다. 화가 없는 묶음은 아니다. */
export function isOutlineFlowBatch<T extends ChapterKindFields>(chapters: readonly T[], batchId: string): boolean {
  const inBatch = chapters.filter((chapter) => chapter.batchId === batchId);
  return inBatch.length > 0 && inBatch.every(isOutlineFlowChapter);
}
