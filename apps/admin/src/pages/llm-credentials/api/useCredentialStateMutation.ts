import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredential } from "../model/credential";
import { invalidateCredentials, reloadIfListStale, replaceCredential } from "./cache";

/** 켜기(소진 해제 포함)·끄기. 켜기가 막히면 409 와 그 이유가 오고, 미리 계산해 둔 막힘이 낡았다는 뜻이라 목록을 다시 받는다. */
export type CredentialStateAction = "enable" | "disable";

type StateVariables = { id: string; action: CredentialStateAction };

export function useCredentialStateMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredential, ApiError, StateVariables>({
    mutationFn: async ({ id, action }) =>
      (await apiClient.post<AdminLlmCredential>(`/admin/llm-credentials/${id}/${action}`)).data,
    onSuccess: (credential) => {
      replaceCredential(queryClient, credential);
      void invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
