import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "../api/client";

type PresignedUploadResponse = components["schemas"]["PresignedUploadResponse"];
type AssetCompleteResponse = components["schemas"]["AssetCompleteResponse"];
export type AssetPurpose = components["schemas"]["AssetPurpose"];

/**
 * techspec-backend-media.md §1의 업로드 3단계(presigned URL 발급 → S3 직접 PUT → 완료 확인)를
 * 감싼 유틸. S3로의 PUT은 우리 API가 아니라 발급받은 절대 URL로 직접 나가야 하므로(쿠키/공통 헤더가
 * 불필요하고 응답도 FastAPI 에러 포맷이 아니다) `apiClient`가 아닌 `fetch`를 그대로 쓴다.
 */
export async function uploadAsset(file: File, purpose: AssetPurpose): Promise<string> {
  const { data: presigned } = await apiClient.post<PresignedUploadResponse>(
    "/assets/presigned-upload",
    { contentType: file.type, purpose },
  );

  const putResponse = await fetch(presigned.uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  });
  if (!putResponse.ok) {
    throw new Error("Failed to upload file to storage");
  }

  const { data: completed } = await apiClient.post<AssetCompleteResponse>(
    `/assets/${presigned.assetId}/complete`,
  );
  return completed.assetId;
}
