/**
 * 미디어 북 칸 썸네일 주소를 고르는 규칙.
 *
 * 서버는 같은 15분 구간 안에서는 같은 자산에 같은 서명 주소를 주지만, 구간이 바뀐 뒤의 자동저장 응답에는 같은
 * 그림도 다른 주소로 온다. 그때마다 `<img src>` 를 바꾸면 같은 그림을 다시 받느라 배치표가 깜빡이므로, 같은
 * 자산이면 이미 받은 주소를 계속 쓴다 — 단 서명 주소는 받은 뒤 최소 15분만 유효하므로 받은 지
 * `THUMBNAIL_URL_REUSE_MS`(그보다 짧다)가 지난 주소는 새 주소가 오면 바꾼다. 이 기기에서 방금 올린 파일의
 * 로컬 주소(objectURL)는 만료가 없어 계속 쓴다.
 */
export const THUMBNAIL_URL_REUSE_MS = 10 * 60 * 1000;

export type ThumbnailUrlEntry = {
  url: string;
  receivedAt: number;
  /** 서명 주소처럼 시간이 지나면 못 쓰게 되는 주소인가. */
  canExpire: boolean;
};

export function nextThumbnailUrlEntry(
  current: ThumbnailUrlEntry | undefined,
  offeredUrl: string | undefined,
  now: number,
): ThumbnailUrlEntry | undefined {
  if (current !== undefined && (!current.canExpire || now - current.receivedAt < THUMBNAIL_URL_REUSE_MS)) return current;
  // 새 주소가 없거나 지금 쓰는 바로 그 주소면 받은 시각을 갱신하지 않는다 — 같은 주소에 새로 받은 것처럼 시각을
  // 찍으면, 저장이 없는 동안 렌더마다 만료 직전 주소의 수명이 늘어나 그 뒤에 온 새 주소를 밀어낸다.
  if (offeredUrl === undefined || offeredUrl === "" || offeredUrl === current?.url) return current;
  return { url: offeredUrl, receivedAt: now, canExpire: true };
}
