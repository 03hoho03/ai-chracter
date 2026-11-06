import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredential, AdminLlmCredentialSecretRequest } from "../model/credential";
import { invalidateCredentials, reloadIfListStale, replaceCredential } from "./cache";

type ReplaceSecretVariables = { id: string } & AdminLlmCredentialSecretRequest;

/**
 * 키만 바꾼다(같은 조직의 키로만). 추가와 같은 이유로 `gcTime: 0` · `networkMode: "always"` 이고, 부르는 쪽이 제출 처리가 끝날 때마다
 * `reset()` 한다 — 요청 변수가 키 원문이다.
 */
export function useReplaceSecretMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredential, ApiError, ReplaceSecretVariables>({
    mutationFn: async ({ id, apiKey }) =>
      (await apiClient.put<AdminLlmCredential>(`/admin/llm-credentials/${id}/secret`, { apiKey })).data,
    gcTime: 0,
    networkMode: "always",
    onSuccess: (credential) => {
      replaceCredential(queryClient, credential);
      void invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
