import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredential } from "../model/credential";
import { sendCredentialWrite } from "../model/failure";
import { invalidateCredentials, reloadIfListStale, replaceCredential } from "./cache";

/** 켜기(소진 해제 포함)·끄기. 켜기가 막히면 409 와 그 이유가 오고, 미리 계산해 둔 막힘이 낡았다는 뜻이라 목록을 다시 받는다. */
export type CredentialStateAction = "enable" | "disable";

type StateVariables = { id: string; action: CredentialStateAction };

/** 오프라인이면 일시정지하지 않고 바로 실패한다(`networkMode: "always"`) — 멈춘 채 닫히지 않거나 연결이 돌아온 순간 모르게 보내지 않게. */
export function useCredentialStateMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredential, ApiError, StateVariables>({
    mutationFn: ({ id, action }) =>
      sendCredentialWrite(
        async () => (await apiClient.post<AdminLlmCredential>(`/admin/llm-credentials/${id}/${action}`)).data,
      ),
    networkMode: "always",
    onSuccess: (credential) => {
      replaceCredential(queryClient, credential);
      void invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
