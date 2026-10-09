/** 마지막 저장(또는 조회) 응답이 본 상황별 이미지 한 행. `imageUrl` 은 이 칸이 생기기 전 서버의 응답에는 없다. */
export type SavedSituationalImage = { id: string; imageAssetId: string | null; imageUrl?: string | null };

type SituationalImageThumbUrlInput = {
  /** 폼 행의 값 id. */
  itemId: string;
  /** 폼 행의 지금 이미지. */
  image: { assetId: string } | null;
  /** 이 기기에서 방금 올린 그림의 브라우저 사본과 그 자산. */
  local: { assetId: string; url: string } | undefined;
  saved: readonly SavedSituationalImage[];
};

/**
 * 상황별 이미지 썸네일의 표시 주소. 폼 행의 자산과 같은 자산의 주소만 쓴다 — 그림을 바꾼 직후 응답은 아직 옛 자산을
 * 보고 있어서, 행 id 만 보고 서버 주소를 쓰면 저장이 끝날 때까지 옛 그림이 보인다. 이 기기 사본이 앞서고(올린 그 순간부터
 * 있고 만료되지 않는다), 없으면 서버 주소, 둘 다 없으면 `null` 이다.
 */
export function situationalImageThumbUrl({ itemId, image, local, saved }: SituationalImageThumbUrlInput): string | null {
  if (image === null) return null;
  if (local?.assetId === image.assetId) return local.url;
  const savedRow = saved.find((row) => row.id === itemId && row.imageAssetId === image.assetId);
  return savedRow?.imageUrl ?? null;
}
