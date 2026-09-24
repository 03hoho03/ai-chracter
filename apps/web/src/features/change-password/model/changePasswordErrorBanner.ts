import { isSuspendedError, SUSPENDED_ERROR_MESSAGE, type AuthFormErrorBanner } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

/** 비밀번호 변경 실패 → 배너. 판별할 수 없는 실패는 `undefined`이고 호출부가 generic 배너로 보낸다.
 *
 * 어느 문구도 "잠시 후 다시 시도"라고 하지 않는다(backlog J-1) — 401은 세션이 사라져 다시 로그인해야
 * 하고, 400은 입력을 고쳐야 한다. */
export function getChangePasswordErrorBanner(error: unknown): AuthFormErrorBanner | undefined {
  if (!isApiError(error)) return undefined;
  if (error.status === 401) {
    return { message: "세션이 만료됐어요. 다시 로그인해주세요.", shouldShowLoginLink: true };
  }
  // 정지 계정은 다시 로그인해도 막히므로 로그인 링크는 출구가 아니다.
  if (isSuspendedError(error)) return { message: SUSPENDED_ERROR_MESSAGE, shouldShowLoginLink: false };
  if (error.status === 400) return { message: "현재 비밀번호가 올바르지 않아요.", shouldShowLoginLink: false };
  return undefined;
}
