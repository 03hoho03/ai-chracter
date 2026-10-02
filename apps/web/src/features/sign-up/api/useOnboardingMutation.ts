import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import type { SocialProvider } from "@/entities/session";
import { apiClient } from "@/shared/api/client";

type SocialOnboardingRequest = components["schemas"]["SocialOnboardingRequest"];
type SocialOnboardingResponse = components["schemas"]["SocialOnboardingResponse"];

type SocialOnboardingVariables = {
  provider: SocialProvider;
  payload: SocialOnboardingRequest;
};

/** 소셜 가입 마무리. 가입 대기 토큰은 콜백이 심은 HttpOnly 쿠키로 실려 가므로(`apiClient`의
 * `withCredentials`) 요청 본문에는 없다. 두 제공자가 같은 요청·응답 모델을 쓰고 경로만 갈린다. */
export function postSocialOnboarding({ provider, payload }: SocialOnboardingVariables) {
  return apiClient
    .post<SocialOnboardingResponse>(`/auth/onboarding/${provider}`, payload)
    .then((res) => res.data);
}

export function useOnboardingMutation() {
  return useMutation({ mutationFn: postSocialOnboarding });
}
