import { isApiError } from "@/shared/api/client";
import { assertNever } from "@/shared/lib/assertNever";

import { SUSPENDED_ERROR_MESSAGE } from "./suspendedMessage";

export type AuthFormErrorBanner = {
  message: string;
  /** 배너 안에 `/login` 링크를 둘지 — 이 폼을 다시 제출해서는 빠져나갈 수 없는 실패다. */
  showsLoginLink: boolean;
};

/** RHF root 에러의 `type` — 컴포넌트는 이 표식으로 배너 안에 로그인 링크를 그릴지 안다
 * (선례: `EmailVerifyStep`의 `type: "server"`). */
export const LOGIN_LINK_ERROR_TYPE = "login-link";

/** 인증 폼 두 곳의 (엔드포인트, status) → 배너. 판별할 수 없는 실패는 `null`이고 호출부가 기존
 * fallback(온보딩은 toast, 비밀번호 변경은 generic 배너)으로 보낸다.
 *
 * 분기는 status로 한다 — 409의 detail `"Email already registered"`는 `/auth/signup`에서 "이미 가입된
 * 이메일"이라는 다른 뜻으로도 쓰여 문자열로 가르면 오분류된다. 예외는 403 하나: 같은 403을 재동의
 * 게이트(`{code: "LEGAL_RECONSENT_REQUIRED"}`)도 내므로 정지는 `LoginForm` 선례대로 detail까지 본다.
 *
 * 어느 문구도 "잠시 후 다시 시도"라고 하지 않는다(backlog J-1) — 기다려서 풀리는 실패가 없다. 400은
 * 가입 토큰이 이미 없고, 409는 탈퇴일로부터 1년(BE `_reregistration_blocked`)이 지나야 풀리고, 401은
 * 세션이 사라져 다시 로그인해야 한다. */
export function getAuthFormErrorBanner(
  error: unknown,
  surface: "onboarding-google" | "change-password",
): AuthFormErrorBanner | null {
  if (!isApiError(error)) return null;
  const isSuspended = error.status === 403 && error.detail === "Account suspended";

  switch (surface) {
    case "onboarding-google":
      // 구글 가입은 로그인 화면의 "구글로 로그인"에서 다시 시작되므로 세 실패 모두 그리로 보낸다(Q-10).
      if (error.status === 400) {
        return { message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.", showsLoginLink: true };
      }
      if (error.status === 409) {
        return {
          message:
            "탈퇴 후 1년이 지나지 않은 이메일이라 다시 가입할 수 없어요. 탈퇴일로부터 1년이 지나면 다시 가입할 수 있어요.",
          showsLoginLink: true,
        };
      }
      if (isSuspended) return { message: SUSPENDED_ERROR_MESSAGE, showsLoginLink: true };
      return null;
    case "change-password":
      if (error.status === 401) {
        return { message: "세션이 만료됐어요. 다시 로그인해주세요.", showsLoginLink: true };
      }
      // 정지 계정은 다시 로그인해도 막히므로 로그인 링크는 출구가 아니다.
      if (isSuspended) return { message: SUSPENDED_ERROR_MESSAGE, showsLoginLink: false };
      if (error.status === 400) return { message: "현재 비밀번호가 올바르지 않아요.", showsLoginLink: false };
      return null;
    default:
      return assertNever(surface);
  }
}
