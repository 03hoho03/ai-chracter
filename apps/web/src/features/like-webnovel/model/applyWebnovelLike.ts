/** 좋아요 요청이 성공한 뒤 작품 정보 캐시에 그 결과를 쓴다. 캐시가 이미 그 값이면(다시 받은 응답이 먼저 왔다) 수를
 * 두 번 바꾸지 않는다. 수는 0 밑으로 내려가지 않는다. */
export function applyWebnovelLike<T extends { liked: boolean; likeCount: number }>(
  detail: T | undefined,
  isLiked: boolean,
): T | undefined {
  if (detail === undefined || detail.liked === isLiked) return detail;
  return { ...detail, liked: isLiked, likeCount: Math.max(detail.likeCount + (isLiked ? 1 : -1), 0) };
}
