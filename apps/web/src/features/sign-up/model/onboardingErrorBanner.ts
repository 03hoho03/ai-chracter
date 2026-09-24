import { isSuspendedError, SUSPENDED_ERROR_MESSAGE, type AuthFormErrorBanner } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

/** 구글 온보딩(`POST /auth/onboarding/google`) 실패 → 배너. 판별할 수 없는 실패는 `undefined`이고
 * 호출부가 기존 fallback(toast)으로 보낸다.
 *
 * 분기는 status로 한다 — 409의 detail `"Email already registered"`는 `/auth/signup`에서 "이미 가입된
 * 이메일"이라는 다른 뜻으로도 쓰여 문자열로 가르면 오분류된다. 예외는 403 하나(`isSuspendedError`).
 *
 * 어느 문구도 "잠시 후 다시 시도"라고 하지 않는다(backlog J-1) — 400은 가입 토큰이 이미 없고, 409는
 * 탈퇴일로부터 1년(BE `_reregistration_blocked`)이 지나야 풀린다. 구글 가입은 로그인 화면의 "구글로
 * 로그인"에서 다시 시작되므로 세 실패 모두 그리로 보낸다(Q-10). */
export function getOnboardingErrorBanner(error: unknown): AuthFormErrorBanner | undefined {
  if (!isApiError(error)) return undefined;
  if (error.status === 400) {
    return { message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.", shouldShowLoginLink: true };
  }
  if (error.status === 409) {
    return {
      message:
        "탈퇴 후 1년이 지나지 않은 이메일이라 다시 가입할 수 없어요. 탈퇴일로부터 1년이 지나면 다시 가입할 수 있어요.",
      shouldShowLoginLink: true,
    };
  }
  if (isSuspendedError(error)) return { message: SUSPENDED_ERROR_MESSAGE, shouldShowLoginLink: true };
  return undefined;
}
