import { isApiError } from "@/shared/api/client";

/** 상위 모델 허용이 없다는 403. 기능이 꺼졌을 때·명단에서 빠졌을 때·허용을 거뒀을 때 모두 같은 코드다. 정지 403 은
 * `detail` 이 문자열이라 객체인지부터 본다. */
export function isChatModelNotAllowedError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 403 || !error.detail || typeof error.detail !== "object") return false;
  return "code" in error.detail && error.detail.code === "CHAT_MODEL_NOT_ALLOWED";
}

/** 그 403 을 받았을 때 이용자에게 보이는 문장. 대화방에서 모델을 바꿀 때와 미리보기를 상위 모델로 시작할 때가 같은 문장이다. */
export const CHAT_MODEL_NOT_ALLOWED_MESSAGE = "이 모델을 지금 이 계정에서 쓸 수 없어요.";
