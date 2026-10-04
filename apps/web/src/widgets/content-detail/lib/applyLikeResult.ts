/** 좋아요 요청이 성공한 뒤 상세 캐시에 쓸 값. 응답이 204라 바디가 없으므로 보낸 값으로 캐시를 직접 고친다.
 * 숫자는 캐시가 아직 반대 값일 때만 ±1 한다 — 다른 이유로 먼저 도착한 리페치가 이미 새 값을 써 두었다면
 * 그 숫자에는 이번 요청이 반영돼 있어 한 번 더 더하면 두 번 센다. */
export function applyLikeResult<T extends { isLiked: boolean; likeCount: number }>(
  entry: T | undefined,
  isLiked: boolean,
): T | undefined {
  if (entry === undefined || entry.isLiked === isLiked) return entry;
  return { ...entry, isLiked, likeCount: entry.likeCount + (isLiked ? 1 : -1) };
}
