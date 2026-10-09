import type { NovelChapterSummary, NovelReadingPositionRequest } from "@/entities/novel";

type ReadableChapter = Pick<NovelChapterSummary, "id" | "finishedReading" | "readingPosition">;

/**
 * 이 화를 떠날 때 마지막으로 잰 자리를 상세 캐시의 그 화에 먼저 써 둔다. 저장 응답에는 본문이 없어 떠날 때 상세를
 * 다시 받게 표시하는데, 다시 받기가 오기 전에 같은 화로 돌아오면(3화 → 4화 → 3화) 낡은 캐시의 자리로 되돌려 방금
 * 읽던 자리를 잃는다. 다 읽음은 한 번 참이면 서버처럼 되돌리지 않는다. 상세나 그 화가 없으면 그대로 돌려준다.
 */
export function withChapterReadingPosition<C extends ReadableChapter, D extends { chapters: C[] }>(
  detail: D | undefined,
  chapterId: string,
  position: NovelReadingPositionRequest,
): D | undefined {
  if (detail === undefined || !detail.chapters.some((chapter) => chapter.id === chapterId)) return detail;
  return {
    ...detail,
    chapters: detail.chapters.map((chapter) => {
      if (chapter.id !== chapterId) return chapter;
      const finished = chapter.finishedReading || position.finished;
      return {
        ...chapter,
        finishedReading: finished,
        readingPosition: {
          paragraphIndex: position.paragraphIndex,
          paragraphCount: position.paragraphCount,
          revisionId: position.revisionId,
          finished,
        },
      };
    }),
  };
}
