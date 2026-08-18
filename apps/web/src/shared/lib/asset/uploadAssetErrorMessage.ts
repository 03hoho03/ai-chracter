import { UploadAssetError, type UploadAssetErrorCode } from "./uploadAsset";

/**
 * 업로드 실패 사유별 안내 문구. 사용자가 다음에 뭘 해야 하는지가 사유마다 다르므로
 * (다른 사진 고르기 / 형식 바꾸기 / 그냥 재시도) 하나의 문구로 뭉뚱그리지 않는다.
 */
const MESSAGE_BY_CODE: Record<UploadAssetErrorCode, string> = {
  FILE_TOO_LARGE: "15MB가 넘는 사진은 올릴 수 없어요. 더 작은 사진을 선택해주세요.",
  DECODE_FAILED: "PNG, JPG, WebP 이미지만 올릴 수 있어요.",
  ENCODE_FAILED: "이미지를 처리하지 못했어요. 다른 사진으로 다시 시도해주세요.",
  SIZE_LIMIT_EXCEEDED: "이미지 용량이 너무 커요. 더 작은 사진을 선택해주세요.",
  UPLOAD_FAILED: "업로드 중 연결이 끊겼어요. 잠시 후 다시 시도해주세요.",
};

/** presigned 발급/완료 확인의 `ApiError` 등 `uploadAsset`이 분류하지 못한 실패. */
const FALLBACK_MESSAGE = "이미지 업로드에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 업로드 진입점들이 `catch (error)`에서 그대로 `toast.error(...)`에 넘기는 한국어 카피. */
export function uploadAssetErrorMessage(error: unknown): string {
  return error instanceof UploadAssetError ? MESSAGE_BY_CODE[error.code] : FALLBACK_MESSAGE;
}
