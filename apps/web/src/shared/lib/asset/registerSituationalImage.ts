import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "../api/client";

type RegisterSituationalImageRequest = components["schemas"]["RegisterSituationalImageRequest"];
type SituationalImageResponse = components["schemas"]["SituationalImageResponse"];

/**
 * techspec-builder-character.md §2 — 상황별 이미지의 `imageAssetId`/블러 변형은
 * `PATCH /contents/{id}/draft`가 아니라 이 엔드포인트(US-071)가 전담한다(apps/api CLAUDE.md
 * 참고). `uploadAsset(file, "situational-image")`로 받은 assetId를 이 호출로 등록해야
 * 실제로 그 항목(entityId)에 이미지가 연결된다 — assetId만 폼에 담아두는 것만으로는 서버에
 * 반영되지 않는다.
 */
export async function registerSituationalImage(
  assetId: string,
  payload: RegisterSituationalImageRequest,
): Promise<SituationalImageResponse> {
  const { data } = await apiClient.post<SituationalImageResponse>(
    `/assets/${assetId}/register-situational-image`,
    payload,
  );
  return data;
}
