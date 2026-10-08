import { readChapterReadingPosition, type NovelChapterSummary, type NovelDetailResponse } from "@/entities/novel";

import type { SavedReadingPosition } from "./toRestoreParagraphIndex";

export type ChapterSavedReadingPosition = {
  /** 이 화를 열 때 되돌릴 자리. 없으면 맨 위에서 연다. */
  saved: SavedReadingPosition | undefined;
  /** `saved` 가 없을 때 서버에도 이 화의 자리가 없다고 확신하는가. 아니면 맨 위에서 재기 시작하면 서버에 있던 자리를
   * 0번 문단으로 덮을 수 있어, 이용자가 스스로 스크롤한 뒤부터 잰다. */
  isAbsenceKnown: boolean;
};

/**
 * 읽기 화면이 이 화를 열 때 되돌릴 자리. 상세 화 요약에 그 화의 자리(`readingPosition`)가 실려 오면 그것을 쓰고,
 * 칸이 아예 없는 옛 API 응답이면(web 이 API 보다 먼저 배포됐거나 API 만 되돌렸을 때) 소설 전체의 마지막 읽은 자리
 * (`lastRead`)가 이 화일 때만 그것을 쓴다 — 화별 복원만 빠지고 읽기·저장은 그대로 동작한다. 옛 응답에서 다른 화는
 * 서버에 자리가 있어도 여기서는 모르므로 `isAbsenceKnown` 이 거짓이다.
 */
export function toChapterSavedReadingPosition(
  summary: Pick<NovelChapterSummary, "id"> & Partial<Pick<NovelChapterSummary, "readingPosition">>,
  lastRead: NovelDetailResponse["lastRead"],
): ChapterSavedReadingPosition {
  const position = readChapterReadingPosition(summary);
  if (position !== undefined) return { saved: position ?? undefined, isAbsenceKnown: true };
  if (lastRead !== null && lastRead.chapterId === summary.id) return { saved: lastRead, isAbsenceKnown: true };
  return { saved: undefined, isAbsenceKnown: false };
}
