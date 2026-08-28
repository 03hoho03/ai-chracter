import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

type AdminLoginRequest = components["schemas"]["AdminLoginRequest"];

export function useLoginMutation() {
  return useMutation({
    mutationFn: (payload: AdminLoginRequest) =>
      apiClient.post<void>("/admin/auth/login", payload).then((res) => res.data),
  });
}
