import type { components } from "@ai-character-chat/api-types";

import type { SignUpFormValues } from "./signUpSchema";

type SignupRequest = components["schemas"]["SignupRequest"];
type VerifyEmailRequest = components["schemas"]["VerifyEmailRequest"];
type LoginRequest = components["schemas"]["LoginRequest"];
type ResendVerificationCodeRequest = components["schemas"]["ResendVerificationCodeRequest"];
type OnboardingGoogleRequest = components["schemas"]["OnboardingGoogleRequest"];

export function toSignupRequest(values: SignUpFormValues): SignupRequest {
  return {
    email: values.email,
    password: values.password,
    nickname: values.nickname,
    birthDate: values.birthDate,
    termsAgreed: values.termsAgreed,
    privacyAgreed: values.privacyAgreed,
    transferAgreed: values.transferAgreed,
  };
}

export function toVerifyEmailRequest(values: SignUpFormValues): VerifyEmailRequest {
  return { email: values.email, code: values.emailVerificationCode };
}

export function toSignUpLoginRequest(values: SignUpFormValues): LoginRequest {
  return { email: values.email, password: values.password };
}

export function toResendVerificationCodeRequest(email: string): ResendVerificationCodeRequest {
  return { email };
}

export function toOnboardingGoogleRequest(
  values: SignUpFormValues,
  token: string,
): OnboardingGoogleRequest {
  return {
    token,
    nickname: values.nickname,
    birthDate: values.birthDate,
    termsAgreed: values.termsAgreed,
    privacyAgreed: values.privacyAgreed,
    transferAgreed: values.transferAgreed,
  };
}
