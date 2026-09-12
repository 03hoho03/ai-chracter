import type { components } from "@ai-character-chat/api-types";

import type { SignUpFormValues } from "@/entities/registration";

type OnboardingGoogleRequest = components["schemas"]["OnboardingGoogleRequest"];
type GuardianConsentRequest = components["schemas"]["GuardianConsentRequest"];

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
  };
}

export function toGuardianConsentRequest(values: SignUpFormValues): GuardianConsentRequest {
  return {
    email: values.email,
    guardianName: values.guardian.name,
    guardianContact: values.guardian.contact,
    consentAgreed: values.guardian.consentAgreed,
  };
}
