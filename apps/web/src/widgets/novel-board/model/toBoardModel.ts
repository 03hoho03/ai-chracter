import {
  isChapterRegenerating,
  readChapterReadingPosition,
  toBatchRangeLabel,
  type NovelChapterSummary,
  type NovelCharacterResponse,
  type NovelDetailResponse,
  type NovelPublicationStatus,
} from "@/entities/novel";

import type { BoardEpisode, BoardModel, EpisodeReadState } from "./boardNode";

/** 화 카드의 읽은 진행. 다 읽은 화가 먼저다 — 다 읽은 뒤 앞부분을 다시 읽어도 서버가 다 읽음으로 남긴다. 읽던 자리의
 * 비율은 그 자리 문단까지 앞에 있는 문단의 몫이라 다 읽지 않은 화는 100% 가 되지 않는다(99 로 자른다). */
export function toEpisodeReadState(
  chapter: Pick<NovelChapterSummary, "finishedReading"> & Partial<Pick<NovelChapterSummary, "readingPosition">>,
): EpisodeReadState {
  if (chapter.finishedReading) return { kind: "finished" };
  // 화별 자리를 싣기 전의 API 응답이면 칸이 없다 — 읽는 중 비율을 모르니 읽지 않은 화로 그린다.
  const position = readChapterReadingPosition(chapter) ?? null;
  if (position === null || position.paragraphCount <= 0) return { kind: "unread" };
  const percent = Math.round((position.paragraphIndex / position.paragraphCount) * 100);
  return { kind: "reading", percent: Math.min(Math.max(percent, 0), 99) };
}

/** 화 카드의 노벨 공개 표시. 지금 노벨에 공개 중인 소설의 공개한 화만 — 공개를 거둔 소설은 독자에게 보이지 않아
 * 표시하지 않는다. 공개 상태를 모르면(받기 전·못 받음) 없다. */
export function toPublicMark(
  publication: Pick<NovelPublicationStatus, "visibility" | "publishedChapterCount" | "changedChapterOrdinals"> | undefined,
  ordinal: number,
): BoardEpisode["publicMark"] {
  if (publication?.visibility !== "public" || ordinal > publication.publishedChapterCount) return undefined;
  return publication.changedChapterOrdinals.includes(ordinal) ? "changed" : "published";
}

/**
 * 상세와 인물 목록 → 보드 입력. 보드는 두 쿼리로 그린다 — 인물은 상세에 없고 따로 받는다. 인물이 아직 없거나 받지
 * 못했으면(`undefined`) 인물 레인 없이 화 열만 그린다.
 */
export function toBoardModel(
  novel: Pick<NovelDetailResponse, "batches" | "chapters" | "settingNotes" | "pendingAiEdits" | "activeJob">,
  characters: readonly NovelCharacterResponse[] | undefined,
  publication?: Pick<NovelPublicationStatus, "visibility" | "publishedChapterCount" | "changedChapterOrdinals">,
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
      publicMark: toPublicMark(publication, chapter.ordinal),
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
