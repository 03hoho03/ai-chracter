import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredential, AdminLlmCredentialUpdateRequest } from "../model/credential";
import { invalidateCredentials, reloadIfListStale, replaceCredential } from "./cache";

type UpdateVariables = { id: string; body: AdminLlmCredentialUpdateRequest };

/** 이름·충전액·임계만 고친다. 보내지 않은 칸은 그대로라, 충전액 칸을 싣지 않은 요청은 사용액 기준을 건드리지 않는다.
 * 오프라인이면 일시정지하지 않고 바로 실패한다(`networkMode: "always"`) — 멈춘 채 닫히지 않거나 연결이 돌아온 순간 모르게 보내지 않게. */
export function useUpdateCredentialMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredential, ApiError, UpdateVariables>({
    mutationFn: async ({ id, body }) =>
      (await apiClient.patch<AdminLlmCredential>(`/admin/llm-credentials/${id}`, body)).data,
    networkMode: "always",
    onSuccess: (credential) => {
      replaceCredential(queryClient, credential);
      void invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
