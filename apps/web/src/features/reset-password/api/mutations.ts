import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

type PasswordResetConfirmRequest = components["schemas"]["PasswordResetConfirmRequest"];

export function useConfirmPasswordResetMutation() {
  return useMutation({
    mutationFn: (payload: PasswordResetConfirmRequest) =>
      apiClient.post<void>("/auth/password-reset/confirm", payload).then((res) => res.data),
  });
}
