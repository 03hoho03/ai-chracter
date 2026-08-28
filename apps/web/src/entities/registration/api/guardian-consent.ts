import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

type GuardianConsentRequest = components["schemas"]["GuardianConsentRequest"];

export function useGuardianConsentMutation() {
  return useMutation({
    mutationFn: (payload: GuardianConsentRequest) =>
      apiClient.post<void>("/auth/guardian-consent", payload).then((res) => res.data),
  });
}
