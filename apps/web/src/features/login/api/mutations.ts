import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

type LoginRequest = components["schemas"]["LoginRequest"];

export function useLoginMutation() {
  return useMutation({
    mutationFn: (payload: LoginRequest) =>
      apiClient.post<void>("/auth/login", payload).then((res) => res.data),
  });
}
