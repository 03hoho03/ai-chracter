import type { NovelChapterReadingPosition, NovelChapterSummary } from "../api/useNovelQuery";

/**
 * 상세 화 요약의 그 화 읽은 자리. `null` 은 읽은 적 없음, `undefined` 는 **응답에 그 칸이 아예 없음**이다 — 화별 읽은
 * 자리를 싣기 전의 API 가 준 응답이다. web 과 API 는 따로 배포되고 따로 되돌려지므로(Pages 가 API 보다 먼저 끝나거나
 * API 만 되돌린 사이) 새 화면이 옛 응답을 받을 수 있다. 생성 타입은 그 칸을 필수로 적지만 여기서는 없을 수 있는
 * 칸으로 받아 한 번 가른다 — 칸을 바로 읽는 곳은 옛 응답에서 `undefined.paragraphCount` 로 화면을 통째로 죽였다.
 */
export function readChapterReadingPosition(
  chapter: Partial<Pick<NovelChapterSummary, "readingPosition">>,
): NovelChapterReadingPosition | null | undefined {
  return chapter.readingPosition;
}
