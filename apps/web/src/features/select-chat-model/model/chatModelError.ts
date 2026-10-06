import { isApiError } from "@/shared/api/client";

/** 상위 모델 허용이 없다는 403. 기능이 꺼졌을 때·명단에서 빠졌을 때·허용을 거뒀을 때 모두 같은 코드다. 정지 403 은
 * `detail` 이 문자열이라 객체인지부터 본다. */
export function isChatModelNotAllowedError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 403 || !error.detail || typeof error.detail !== "object") return false;
  return "code" in error.detail && error.detail.code === "CHAT_MODEL_NOT_ALLOWED";
}
