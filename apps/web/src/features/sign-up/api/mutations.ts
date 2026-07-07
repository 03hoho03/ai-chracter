import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

type SignupRequest = components["schemas"]["SignupRequest"];
type SignupResponse = components["schemas"]["SignupResponse"];
type VerifyEmailRequest = components["schemas"]["VerifyEmailRequest"];
type VerifyEmailResponse = components["schemas"]["VerifyEmailResponse"];
type ResendVerificationCodeRequest = components["schemas"]["ResendVerificationCodeRequest"];
type GuardianConsentRequest = components["schemas"]["GuardianConsentRequest"];
type LoginRequest = components["schemas"]["LoginRequest"];

export function useSignUpMutation() {
  return useMutation({
    mutationFn: (payload: SignupRequest) =>
      apiClient.post<SignupResponse>("/auth/signup", payload).then((res) => res.data),
  });
}

export function useVerifyEmailMutation() {
  return useMutation({
    mutationFn: (payload: VerifyEmailRequest) =>
      apiClient.post<VerifyEmailResponse>("/auth/verify-email", payload).then((res) => res.data),
  });
}

export function useResendVerificationCodeMutation() {
  return useMutation({
    mutationFn: (payload: ResendVerificationCodeRequest) =>
      apiClient.post<void>("/auth/resend-verification-code", payload).then((res) => res.data),
  });
}

export function useGuardianConsentMutation() {
  return useMutation({
    mutationFn: (payload: GuardianConsentRequest) =>
      apiClient.post<void>("/auth/guardian-consent", payload).then((res) => res.data),
  });
}

/**
 * 회원가입 위저드 전용 재사용: 이메일 인증만으로는 세션이 발급되지 않고(성인 경로),
 * guardian-consent만 세션을 발급한다(apps/api/CLAUDE.md 참고). 성인 경로는 이메일 인증
 * 성공 직후 폼에 남아있는 email/password로 이 로그인 뮤테이션을 호출해 세션을 발급시킨다.
 */
export function useSignUpLoginMutation() {
  return useMutation({
    mutationFn: (payload: LoginRequest) =>
      apiClient.post<void>("/auth/login", payload).then((res) => res.data),
  });
}
