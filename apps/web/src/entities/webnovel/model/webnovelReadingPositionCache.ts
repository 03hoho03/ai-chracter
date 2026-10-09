import type { WebnovelReadingPositionRequest } from "../api/saveWebnovelReadingPosition";
import type { WebnovelDetailResponse } from "../api/useWebnovelQuery";

/** 노벨 화를 떠날 때 마지막으로 잰 자리를 작품 정보 캐시의 그 화에 먼저 써 둔다. 저장 응답에는 본문이 없어 떠날 때
 * 작품 정보를 다시 받게 표시하는데, 그 전에 같은 화로 돌아오면 낡은 자리로 되돌려 방금 읽던 자리를 잃는다(소유자
 * 읽기 화면과 같은 처방). 다 읽음은 한 번 참이면 서버처럼 되돌리지 않는다. 작품 정보나 그 화가 없으면 그대로 돌려준다. */
export function withWebnovelReadingPosition(
  detail: WebnovelDetailResponse | undefined,
  chapterId: string,
  position: WebnovelReadingPositionRequest,
): WebnovelDetailResponse | undefined {
  if (detail === undefined || !detail.chapters.some((chapter) => chapter.id === chapterId)) return detail;
  return {
    ...detail,
    chapters: detail.chapters.map((chapter) => {
      if (chapter.id !== chapterId) return chapter;
      return {
        ...chapter,
        readingPosition: {
          paragraphIndex: position.paragraphIndex,
          paragraphCount: position.paragraphCount,
          edition: position.edition,
          finished: (chapter.readingPosition?.finished ?? false) || position.finished,
        },
      };
    }),
  };
}
