import type { components } from "@ai-character-chat/api-types";

import {
  ResizeImageError,
  resizeImage,
  type ResizeImageErrorCode,
  type ResizeSpec,
} from "@/shared/lib/asset/resizeImage";

import { apiClient, isApiError } from "../client";

type PresignedUploadResponse = components["schemas"]["PresignedUploadResponse"];
/** 원본 픽셀 좌표의 크롭 영역. 서버가 모든 프레임에 같은 크롭을 건다. */
export type UploadCrop = components["schemas"]["UploadCrop"];

/** 업로드 직전까지 가공한 결과. 움직이는 대표 이미지는 canvas 로 자르면 첫 프레임만 남아, 원본 파일과 크롭 영역을 따로
 * 들고 와 서버가 자르게 한다(`crop`). 정지 그림은 이미 자른 파일만 있다. */
export type PreparedUpload = { file: File; crop?: UploadCrop };
type AssetCompleteResponse = components["schemas"]["AssetCompleteResponse"];
export type AssetPurpose = components["schemas"]["AssetPurpose"];

/**
 * purpose별 리사이즈 규격 — 아바타/카드는 작은 슬롯에만 그려지고, 채팅에 크게 뜨는 상황별 이미지만 길게 남긴다.
 * `inquiry-attachment`의 2048/0.90은 이 저장소의 새 최대치다(기존 최대 1536, 최고 품질 0.82) —
 * 문의 첨부(버그 신고 스크린샷)의 가치는 작은 글자를 읽는 데 있어 다른 용도보다 원본을 더 많이 남긴다.
 * 이 dict는 `Record<AssetPurpose, ...>`라 값 추가를 빠뜨리면 컴파일 에러로 잡힌다 — BE의
 * `UPLOAD_SIZE_LIMIT_BYTES`(`dict[AssetPurpose, int]`)는 mypy가 이 전수성을 검사하지 않아 사람이 지켜야 한다
 * (apps/api/src/api/assets/schemas.py 주석 참고).
 */
const RESIZE_SPEC_BY_PURPOSE: Record<AssetPurpose, ResizeSpec> = {
  "profile-image": { maxEdge: 512, quality: 0.82 },
  "content-thumbnail": { maxEdge: 1024, quality: 0.82 },
  "situational-image": { maxEdge: 1536, quality: 0.82 },
  "inquiry-attachment": { maxEdge: 2048, quality: 0.9 },
};

/**
 * 리사이즈하지 않고 원본 바이트를 그대로 올리는 형식. `resizeImage`는 canvas에 첫 프레임만 그려 GIF를 정지 그림으로
 * 바꾸는데, 문의 첨부는 버그를 녹화한 움직임 자체가 신고 내용이고 상황 이미지는 채팅에서 원본 그대로 움직여야 한다.
 * 원본 그대로여도 아래 용량 상한은 같게 걸리고, 서버는 업로드 완료 때 바이트에서 형식을 읽어 저장한다. 대표 이미지는
 * 크롭 모달이 canvas 로 한 장만 그려 움직임을 지우므로, 원본과 크롭 영역(`crop`)을 함께 보내 서버가 모든 프레임을 자른다.
 */
const KEEP_ORIGINAL_TYPES_BY_PURPOSE: Partial<Record<AssetPurpose, readonly string[]>> = {
  "inquiry-attachment": ["image/gif"],
  "situational-image": ["image/gif"],
  "content-thumbnail": ["image/gif"],
};

/** 서버의 `UPLOAD_SIZE_LIMIT_BYTES`(apps/api/src/api/assets/schemas.py)와 같은 값 — 리사이즈 *결과물*에 건다. */
export const MAX_UPLOAD_BYTES_BY_PURPOSE: Record<AssetPurpose, number> = {
  "profile-image": 2 * 1024 * 1024,
  "content-thumbnail": 5 * 1024 * 1024,
  "situational-image": 5 * 1024 * 1024,
  "inquiry-attachment": 5 * 1024 * 1024,
};

export type UploadAssetErrorCode =
  | ResizeImageErrorCode
  /** 리사이즈 결과가 purpose별 상한을 넘음 */
  | "SIZE_LIMIT_EXCEEDED"
  /** 서버가 픽셀 수 상한으로 거절함 — 리사이즈 없이 올리는 GIF가 프레임 수 × 크기 상한을 넘을 때 닿는다 */
  | "PIXEL_LIMIT_EXCEEDED"
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
 * 업로드 3단계(presigned URL 발급 → S3 직접 PUT → 완료 확인)를
 * 감싼 유틸. S3로의 PUT은 우리 API가 아니라 발급받은 절대 URL로 직접 나가야 하므로(쿠키/공통 헤더가
 * 불필요하고 응답도 FastAPI 에러 포맷이 아니다) `apiClient`가 아닌 `fetch`를 그대로 쓴다.
 *
 * PUT 전에 `resizeImage`를 거치므로 올라가는 바이트는 `image/webp`이고(예외는 `KEEP_ORIGINAL_TYPES_BY_PURPOSE`),
 * presigned 요청의 contentType과 PUT의 Content-Type도 올라가는 파일의 타입으로 맞춘다.
 */
export async function uploadAsset(file: File, purpose: AssetPurpose, crop?: UploadCrop): Promise<string> {
  const resized = await resizeForUpload(file, purpose);

  const maxBytes = MAX_UPLOAD_BYTES_BY_PURPOSE[purpose];
  if (resized.size > maxBytes) {
    throw new UploadAssetError("SIZE_LIMIT_EXCEEDED", `Resized file exceeds ${maxBytes} bytes`);
  }

  const { data: presigned } = await apiClient.post<PresignedUploadResponse>(
    "/assets/presigned-upload",
    { contentType: resized.type, purpose, ...(crop && { crop }) },
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

  try {
    const { data: completed } = await apiClient.post<AssetCompleteResponse>(`/assets/${presigned.assetId}/complete`);
    return completed.assetId;
  } catch (error) {
    if (isPixelLimitRejection(error)) throw new UploadAssetError("PIXEL_LIMIT_EXCEEDED", "Image exceeds the pixel limit");
    throw error;
  }
}

/** 업로드 완료의 400 중 픽셀 수 상한 거절(`{maxPixels, actualPixels}`). 그 밖의 실패는 호출부의 일반 문구로 간다. */
export function isPixelLimitRejection(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 400) return false;
  const { detail } = error;
  return typeof detail === "object" && detail !== null && !Array.isArray(detail) && "maxPixels" in detail;
}

/** 호출부가 두 에러 타입을 갈라 보지 않도록 리사이즈 실패도 code를 승계해 `UploadAssetError`로 합친다. */
async function resizeForUpload(file: File, purpose: AssetPurpose): Promise<File> {
  if (KEEP_ORIGINAL_TYPES_BY_PURPOSE[purpose]?.includes(file.type)) return file;
  try {
    return await resizeImage(file, RESIZE_SPEC_BY_PURPOSE[purpose]);
  } catch (error) {
    if (error instanceof ResizeImageError) {
      throw new UploadAssetError(error.code, error.message);
    }
    throw error;
  }
}
