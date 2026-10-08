import type { components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

export type StartIdentityVerificationResponse = components["schemas"]["StartIdentityVerificationResponse"];

/** 인증 id 를 받아 이 계정에 묶는다. 상점 id·채널키는 웹 빌드에 넣지 않고 이 응답으로만 받는다. */
export function useStartIdentityVerificationMutation() {
  return useMutation({
    mutationFn: () =>
      apiClient.post<StartIdentityVerificationResponse>("/me/identity-verifications").then((res) => res.data),
  });
}
