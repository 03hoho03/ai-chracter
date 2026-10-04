import {
  formatAuthRateLimitMessage,
  getAuthRateLimit,
  isSuspendedError,
  SUSPENDED_ERROR_MESSAGE,
  type AuthFormErrorBanner,
} from "@/entities/session";
import { isApiError } from "@/shared/api/client";

/** 비밀번호 변경 실패 → 배너. 판별할 수 없는 실패는 `undefined`이고 호출부가 generic 배너로 보낸다.
 *
 * 어느 문구도 "잠시 후 다시 시도"라고 하지 않는다 — 401은 세션이 사라져 다시 로그인해야
 * 하고, 400은 입력을 고쳐야 한다(비밀번호 없는 계정의 400은 폼으로 고칠 수 없지만 기다려서 풀리지도 않는다). */
export function getChangePasswordErrorBanner(error: unknown): AuthFormErrorBanner | undefined {
  if (!isApiError(error)) return undefined;
  if (error.status === 401) {
    return { message: "세션이 만료됐어요. 다시 로그인해주세요.", shouldShowLoginLink: true };
  }
  // 정지 계정은 다시 로그인해도 막히므로 로그인 링크는 출구가 아니다.
  if (isSuspendedError(error)) return { message: SUSPENDED_ERROR_MESSAGE, shouldShowLoginLink: false };
  // 소셜로만 가입한 계정은 바꿀 비밀번호가 없다. 마이페이지가 이 계정에는 폼을 아예 그리지 않으므로 방어용이다 —
  // 세션의 `hasPassword`가 낡아 폼이 보인 채 제출됐을 때 "현재 비밀번호가 틀렸다"는 거짓 안내를 막는다.
  if (error.status === 400 && error.detail && typeof error.detail === "object" && error.detail.code === "PASSWORD_NOT_SET") {
    return { message: "소셜 로그인으로 가입한 계정이라 변경할 비밀번호가 없어요.", shouldShowLoginLink: false };
  }
  if (error.status === 400) return { message: "현재 비밀번호가 올바르지 않아요.", shouldShowLoginLink: false };
  // 현재 비밀번호 확인 횟수 상한. 맞는 비밀번호여도 막히므로 오답 문구가 아니라 기다릴 시간을 말한다.
  const rateLimit = getAuthRateLimit(error);
  if (rateLimit) {
    return { message: formatAuthRateLimitMessage(rateLimit, "password-confirm"), shouldShowLoginLink: false };
  }
  return undefined;
}
