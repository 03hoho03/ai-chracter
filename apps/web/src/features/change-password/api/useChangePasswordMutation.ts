import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type ChangePasswordRequest = components["schemas"]["ChangePasswordRequest"];

export function useChangePasswordMutation() {
  return useMutation({
    mutationFn: (payload: ChangePasswordRequest) =>
      apiClient.patch<void>("/me/password", payload).then((res) => res.data),
  });
}
