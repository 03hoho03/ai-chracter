/**
 * 되살린 상황별 이미지의 그림을 서버 행에 다시 등록할지 정한다.
 *
 * - `skip`: 그 행이 없어졌거나(다시 지웠다) 폼 행의 그림이 되살린 그림이 아니다(그 사이 다른 그림을 올렸다). 옛 그림을 등록하면
 *   새 그림을 덮는다.
 * - `wait-description`: 노출할 상황이 비었다. 등록 API 가 빈 상황을 받지 않으므로 상황이 채워질 때까지 미룬다.
 * - `register`: 지금 등록한다.
 */
export type SituationalImageRelinkAction = "skip" | "wait-description" | "register";

export function situationalImageRelinkAction(
  restoredAssetId: string,
  row: { image: { assetId: string } | null; situationDescription: string } | undefined,
): SituationalImageRelinkAction {
  if (row === undefined || row.image?.assetId !== restoredAssetId) return "skip";
  if (row.situationDescription.trim() === "") return "wait-description";
  return "register";
}

/**
 * 다시 등록한 뒤 할 일.
 *
 * - `save`: 폼 행이 아직 그 그림이다. 저장을 한 번 더 일으켜 초안 캐시가 그림 있는 응답으로 끝나게 한다.
 * - `register-current`: 그 사이 폼 행에 다른 그림이 들어왔다. 그 그림의 등록이 이 등록보다 먼저 끝났다면(폼 값은 등록이 끝난
 *   뒤에야 바뀐다) 서버 행을 옛 그림으로 덮은 것이니 지금 그림을 다시 등록한다.
 * - `none`: 행이 없어졌거나 그림이 빠졌다.
 */
export type SituationalImageAfterRelink = "save" | "register-current" | "none";

export function situationalImageAfterRelink(
  registeredAssetId: string,
  currentImage: { assetId: string } | null | undefined,
): SituationalImageAfterRelink {
  if (currentImage === null || currentImage === undefined) return "none";
  return currentImage.assetId === registeredAssetId ? "save" : "register-current";
}
