import type { components } from "@ai-character-chat/api-types";

import { apiClient } from "../api/client";
import {
  ResizeImageError,
  resizeImage,
  type ResizeImageErrorCode,
  type ResizeSpec,
} from "./resizeImage";

type PresignedUploadResponse = components["schemas"]["PresignedUploadResponse"];
type AssetCompleteResponse = components["schemas"]["AssetCompleteResponse"];
export type AssetPurpose = components["schemas"]["AssetPurpose"];

/** purpose별 리사이즈 규격 — 아바타/카드는 작은 슬롯에만 그려지고, 채팅에 크게 뜨는 상황별 이미지만 길게 남긴다. */
const RESIZE_SPEC_BY_PURPOSE: Record<AssetPurpose, ResizeSpec> = {
  "profile-image": { maxEdge: 512, quality: 0.82 },
  "content-thumbnail": { maxEdge: 1024, quality: 0.82 },
  "situational-image": { maxEdge: 1536, quality: 0.82 },
};

/** 서버의 `UPLOAD_SIZE_LIMIT_BYTES`(apps/api/src/api/assets/schemas.py)와 같은 값 — 리사이즈 *결과물*에 건다. */
const MAX_UPLOAD_BYTES_BY_PURPOSE: Record<AssetPurpose, number> = {
  "profile-image": 2 * 1024 * 1024,
  "content-thumbnail": 5 * 1024 * 1024,
  "situational-image": 5 * 1024 * 1024,
};

export type UploadAssetErrorCode =
  | ResizeImageErrorCode
  /** 리사이즈 결과가 purpose별 상한을 넘음 */
  | "SIZE_LIMIT_EXCEEDED"
  /** S3로의 PUT 실패 (네트워크 단절, 서명 만료 등) */
  | "UPLOAD_FAILED";

/** 호출부가 사유별로 다른 안내를 띄울 수 있도록 `code`로 실패를 구분한다. */
export class UploadAssetError extends Error {
  constructor(
    readonly code: UploadAssetErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "UploadAssetError";
  }
}

/**
 * techspec-backend-media.md §1의 업로드 3단계(presigned URL 발급 → S3 직접 PUT → 완료 확인)를
 * 감싼 유틸. S3로의 PUT은 우리 API가 아니라 발급받은 절대 URL로 직접 나가야 하므로(쿠키/공통 헤더가
 * 불필요하고 응답도 FastAPI 에러 포맷이 아니다) `apiClient`가 아닌 `fetch`를 그대로 쓴다.
 *
 * PUT 전에 항상 `resizeImage`를 거치므로 올라가는 바이트는 언제나 `image/webp`이고, presigned 요청의
 * contentType과 PUT의 Content-Type도 그 결과 타입으로 맞춘다(원본 `file.type`을 보내지 않는다).
 */
export async function uploadAsset(file: File, purpose: AssetPurpose): Promise<string> {
  const resized = await resizeForUpload(file, purpose);

  const maxBytes = MAX_UPLOAD_BYTES_BY_PURPOSE[purpose];
  if (resized.size > maxBytes) {
    throw new UploadAssetError("SIZE_LIMIT_EXCEEDED", `Resized file exceeds ${maxBytes} bytes`);
  }

  const { data: presigned } = await apiClient.post<PresignedUploadResponse>(
    "/assets/presigned-upload",
    { contentType: resized.type, purpose },
  );

  // 우리 API 호출(presigned 발급/완료 확인)의 실패는 apiClient가 ApiError로 정규화하므로 그대로 두고,
  // 정규화 밖인 S3 직접 PUT만 UploadAssetError로 감싼다.
  let putResponse: Response;
  try {
    putResponse = await fetch(presigned.uploadUrl, {
      method: "PUT",
      headers: { "Content-Type": resized.type },
      body: resized,
    });
  } catch {
    throw new UploadAssetError("UPLOAD_FAILED", "Failed to reach storage");
  }
  if (!putResponse.ok) {
    throw new UploadAssetError("UPLOAD_FAILED", "Failed to upload file to storage");
  }

  const { data: completed } = await apiClient.post<AssetCompleteResponse>(
    `/assets/${presigned.assetId}/complete`,
  );
  return completed.assetId;
}

/** 호출부가 두 에러 타입을 갈라 보지 않도록 리사이즈 실패도 code를 승계해 `UploadAssetError`로 합친다. */
async function resizeForUpload(file: File, purpose: AssetPurpose): Promise<File> {
  try {
    return await resizeImage(file, RESIZE_SPEC_BY_PURPOSE[purpose]);
  } catch (error) {
    if (error instanceof ResizeImageError) {
      throw new UploadAssetError(error.code, error.message);
    }
    throw error;
  }
}
