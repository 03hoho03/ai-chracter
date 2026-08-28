import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

type OnboardingGoogleRequest = components["schemas"]["OnboardingGoogleRequest"];
type OnboardingGoogleResponse = components["schemas"]["OnboardingGoogleResponse"];

export function useOnboardingGoogleMutation() {
  return useMutation({
    mutationFn: (payload: OnboardingGoogleRequest) =>
      apiClient
        .post<OnboardingGoogleResponse>("/auth/onboarding/google", payload)
        .then((res) => res.data),
  });
}
