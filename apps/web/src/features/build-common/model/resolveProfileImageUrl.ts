/**
 * 이 기기에서 방금 올리거나 고른 대표 이미지의 표시 주소. 어느 자산의 주소인지 함께 들고 있어야 폼 값과 대조된다.
 * `canExpire` 는 시간이 지나면 깨지는 주소인지다 — 고른 그림의 서명 주소는 만료되고, 브라우저 사본(objectURL)은
 * 쥔 쪽이 해제하기 전까지 살아 있다.
 */
export type ProfileImageLocalEntry = { assetId: string; url: string; canExpire: boolean };

type ResolveProfileImageUrlInput = {
  /** 폼의 현재 대표 이미지 값. */
  image: { assetId: string } | null;
  local: ProfileImageLocalEntry | undefined;
  /** 마지막 저장(또는 조회) 응답이 본 대표 이미지. */
  draft: { thumbnailAssetId: string | null; thumbnailUrl: string | null };
};

/**
 * 대표 이미지 칸과 미리보기 카드가 함께 쓸 표시 주소를 폼 값에서 정한다. 서버가 준 주소는 마지막 저장이 본
 * 자산의 주소일 뿐이라, 폼의 자산이 그 뒤에 바뀌었으면 그대로 쓰면 옛 그림이 남는다. 그래서 폼의 자산 ID 와
 * 같은 자산의 주소만 쓰고, 어느 쪽에도 그 자산의 주소가 없으면 옛 그림 대신 빈 칸을 보인다.
 *
 * 같은 자산이면 만료되지 않는 이 기기 사본이 가장 앞선다. 만료되는 이 기기 주소는 서버 주소보다 뒤로 미룬다 —
 * 이 값을 쥔 셸은 빌더를 떠날 때까지 살아 있어 그 주소가 만료된 뒤 새로 그려지는 `<img>` 가 깨질 수 있지만,
 * 서버 주소는 저장·조회 응답이 올 때마다 다시 서명돼 온다.
 */
export function resolveProfileImageUrl({ image, local, draft }: ResolveProfileImageUrlInput): string | null {
  if (image === null) return null;
  const ownLocal = local?.assetId === image.assetId ? local : undefined;
  if (ownLocal !== undefined && !ownLocal.canExpire) return ownLocal.url;
  const savedUrl = draft.thumbnailAssetId === image.assetId ? draft.thumbnailUrl : null;
  return savedUrl ?? ownLocal?.url ?? null;
}
