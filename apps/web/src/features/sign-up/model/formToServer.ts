import type { components } from "@ai-character-chat/api-types";

import type { SignUpFormValues } from "./signUpSchema";

type SignupRequest = components["schemas"]["SignupRequest"];
type VerifyEmailRequest = components["schemas"]["VerifyEmailRequest"];
type LoginRequest = components["schemas"]["LoginRequest"];
type ResendVerificationCodeRequest = components["schemas"]["ResendVerificationCodeRequest"];
type SocialOnboardingRequest = components["schemas"]["SocialOnboardingRequest"];

/** 첫 대화 프로필 이름. 비었으면 필드째 빼서 서버가 프로필을 만들지 않게 한다(닉네임으로 채우지 않는다). */
function toPersonaNameField(personaName: string): { personaName?: string } {
  const name = personaName.trim();
  return name === "" ? {} : { personaName: name };
}

export function toSignupRequest(values: SignUpFormValues): SignupRequest {
  return {
    ...toPersonaNameField(values.personaName),
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

export function toSocialOnboardingRequest(values: SignUpFormValues): SocialOnboardingRequest {
  return {
    ...toPersonaNameField(values.personaName),
    nickname: values.nickname,
    birthDate: values.birthDate,
    termsAgreed: values.termsAgreed,
    privacyAgreed: values.privacyAgreed,
    transferAgreed: values.transferAgreed,
  };
}
