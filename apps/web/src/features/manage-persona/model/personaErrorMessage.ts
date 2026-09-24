import { isApiError } from "@/shared/api/client";

export const GENERIC_PERSONA_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";
export const INVALID_PERSONA_INPUT_MESSAGE = "입력한 내용을 다시 확인해주세요.";

/** 프로필 쓰기 실패 → 사용자 문구.
 *
 * - 409(11번째 생성): BE가 한국어 문구를 `detail` 문자열로 준다 — 그대로 쓴다(개수 상한 사본을 두지 않는다).
 * - 422: pydantic 원문(영문, `"Value error, …"` 접두사)이라 **노출하지 않는다**. 정상 입력은 FE zod가 같은
 *   규칙으로 먼저 막으므로 여기 오는 건 규칙이 어긋났을 때뿐이다.
 * - 그 밖(404·403 영문 디버그 문구 포함): 일반 문구. */
export function personaErrorMessage(error: unknown): string {
  if (!isApiError(error)) return GENERIC_PERSONA_ERROR_MESSAGE;
  if (error.status === 409) return error.message;
  if (error.status === 422) return INVALID_PERSONA_INPUT_MESSAGE;
  return GENERIC_PERSONA_ERROR_MESSAGE;
}
