import type { components } from "@ai-character-chat/api-types";

import type { SignUpFormValues } from "@/entities/registration";

type SignupRequest = components["schemas"]["SignupRequest"];
type VerifyEmailRequest = components["schemas"]["VerifyEmailRequest"];
type LoginRequest = components["schemas"]["LoginRequest"];
type GuardianConsentRequest = components["schemas"]["GuardianConsentRequest"];
type ResendVerificationCodeRequest = components["schemas"]["ResendVerificationCodeRequest"];

export function toSignupRequest(values: SignUpFormValues): SignupRequest {
  return {
    email: values.email,
    password: values.password,
    nickname: values.nickname,
    birthDate: values.birthDate,
    termsAgreed: values.termsAgreed,
    privacyAgreed: values.privacyAgreed,
  };
}

export function toVerifyEmailRequest(values: SignUpFormValues): VerifyEmailRequest {
  return { email: values.email, code: values.emailVerificationCode };
}

export function toSignUpLoginRequest(values: SignUpFormValues): LoginRequest {
  return { email: values.email, password: values.password };
}

export function toGuardianConsentRequest(values: SignUpFormValues): GuardianConsentRequest {
  return {
    email: values.email,
    guardianName: values.guardian.name,
    guardianContact: values.guardian.contact,
    consentAgreed: values.guardian.consentAgreed,
  };
}

export function toResendVerificationCodeRequest(email: string): ResendVerificationCodeRequest {
  return { email };
}
