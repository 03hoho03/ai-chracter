import { isApiError } from "@/shared/api/client";

/** 그 모델을 지금 채팅에서 쓸 수 없다는 403. 상위 모델 총 스위치가 꺼졌을 때와 그 모델이 공개 목록에서 빠졌을 때 같은
 * 코드다(계정마다 갈리지 않는다). 정지 403 은 `detail` 이 문자열이라 객체인지부터 본다. */
export function isChatModelNotAllowedError(error: unknown): boolean {
  if (!isApiError(error) || error.status !== 403 || !error.detail || typeof error.detail !== "object") return false;
  return "code" in error.detail && error.detail.code === "CHAT_MODEL_NOT_ALLOWED";
}

/** 대화방에서 모델을 바꾸다 그 403 을 받았을 때의 문장. 판정이 계정을 보지 않아 "이 계정에서"라고 말하지 않는다. 받은
 * 뒤 모델 목록을 다시 불러오므로 그 사실을 함께 말한다. */
export const CHAT_MODEL_NOT_ALLOWED_MESSAGE = "지금은 이 모델을 쓸 수 없어요. 목록을 새로 불러왔어요.";

/** 미리보기를 그 모델로 시작하다 그 403 을 받았을 때의 문장. 미리보기는 고른 모델을 기본 모델로 되돌리므로 그 사실을 말한다. */
export const PREVIEW_CHAT_MODEL_NOT_ALLOWED_MESSAGE = "지금은 이 모델을 쓸 수 없어 기본 모델로 바꿨어요.";
