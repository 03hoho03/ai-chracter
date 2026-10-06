/** 0 … 1 로 자른다. */
function clampRatio(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

/**
 * 화 안 진행률(하단 바의 얇은 막대). 문서 스크롤 위치를 스크롤할 수 있는 거리로 나눈다. 본문이 화면 안에 다 들어와
 * 스크롤할 거리가 없으면 끝까지 본 것이라 1 이다. iOS 의 고무줄 스크롤이 0 아래·끝 너머 값을 주므로 0 … 1 로 자른다.
 */
export function toEpisodeScrollProgress({
  scrollTop,
  scrollHeight,
  clientHeight,
}: {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}): number {
  const scrollable = scrollHeight - clientHeight;
  if (scrollable <= 0) return 1;
  return clampRatio(scrollTop / scrollable);
}

/** 작품 전체 진행률(목차). 다 읽은 화 수 ÷ 전체 화 수, 화가 없으면 0. */
export function toNovelReadProgress(finishedCount: number, totalCount: number): number {
  if (totalCount <= 0) return 0;
  return clampRatio(finishedCount / totalCount);
}
