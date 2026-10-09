import { BUILDER_SAVE_LIMIT_MESSAGE } from "@/entities/content";
import { isApiError } from "@/shared/api/client";

/**
 * 캐릭터 저장 실패 토스트 문구 — 자동저장과 임시저장 버튼이 함께 쓴다. 서버가 한도 검사로 거절한(422) 저장은 기다려도
 * 풀리지 않으므로 "잠시 후 다시" 대신 줄이라고 말한다. 따로 안내할 이유가 없으면 undefined(호출부의 기본 문구).
 */
export function characterSaveErrorMessage(error: unknown): string | undefined {
  if (isApiError(error) && error.status === 422) return BUILDER_SAVE_LIMIT_MESSAGE;
  return undefined;
}
