import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

type PasswordResetRequestRequest = components["schemas"]["PasswordResetRequestRequest"];

export function useRequestPasswordResetMutation() {
  return useMutation({
    mutationFn: (payload: PasswordResetRequestRequest) =>
      apiClient.post<void>("/auth/password-reset/request", payload).then((res) => res.data),
  });
}
