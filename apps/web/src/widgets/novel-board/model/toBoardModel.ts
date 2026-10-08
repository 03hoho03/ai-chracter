import {
  isChapterRegenerating,
  toBatchRangeLabel,
  type NovelChapterSummary,
  type NovelCharacterResponse,
  type NovelDetailResponse,
} from "@/entities/novel";

import type { BoardModel, EpisodeReadState } from "./boardNode";

/** 화 카드의 읽은 진행. 다 읽은 화가 먼저다 — 다 읽은 뒤 앞부분을 다시 읽어도 서버가 다 읽음으로 남긴다. 읽던 자리의
 * 비율은 그 자리 문단까지 앞에 있는 문단의 몫이라 다 읽지 않은 화는 100% 가 되지 않는다(99 로 자른다). */
export function toEpisodeReadState(
  chapter: Pick<NovelChapterSummary, "finishedReading" | "readingPosition">,
): EpisodeReadState {
  if (chapter.finishedReading) return { kind: "finished" };
  const position = chapter.readingPosition;
  if (position === null || position.paragraphCount <= 0) return { kind: "unread" };
  const percent = Math.round((position.paragraphIndex / position.paragraphCount) * 100);
  return { kind: "reading", percent: Math.min(Math.max(percent, 0), 99) };
}

/**
 * 상세와 인물 목록 → 보드 입력. 보드는 두 쿼리로 그린다 — 인물은 상세에 없고 따로 받는다. 인물이 아직 없거나 받지
 * 못했으면(`undefined`) 인물 레인 없이 화 열만 그린다.
 */
export function toBoardModel(
  novel: Pick<NovelDetailResponse, "batches" | "chapters" | "settingNotes" | "pendingAiEdits" | "activeJob">,
  characters: readonly NovelCharacterResponse[] | undefined,
): BoardModel {
  const pendingChapterIds = new Set(novel.pendingAiEdits.map((edit) => edit.chapterId));
  return {
    batches: novel.batches.map((batch) => ({
      id: batch.id,
      ordinal: batch.ordinal,
      rangeLabel: toBatchRangeLabel(novel.chapters, batch.id),
    })),
    episodes: novel.chapters.map((chapter) => ({
      id: chapter.id,
      batchId: chapter.batchId,
      ordinal: chapter.ordinal,
      title: chapter.title,
      summary: chapter.summary,
      charCount: chapter.charCount,
      readState: toEpisodeReadState(chapter),
      hasPendingAiEdit: pendingChapterIds.has(chapter.id),
      isRegenerating: isChapterRegenerating(novel.activeJob, chapter.id, chapter.batchId),
    })),
    characters: (characters ?? []).map(({ id, name, aliases, memo, chapterIds }) => ({
      id,
      name,
      aliases,
      memo,
      chapterIds,
    })),
    notes: novel.settingNotes,
  };
}
