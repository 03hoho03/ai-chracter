import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredentialCheckResponse } from "../model/credential";
import { invalidateCredentials, reloadIfListStale, replaceCredential } from "./cache";

/** 확인 호출. 모델 id 마다 짧은 요청을 차례로 보내 응답이 늦으면 몇십 초 걸린다. 응답 항목(확인 기록·사용액 포함)을 끼운 뒤에도 다시
 * 받는 것은 기다리는 동안 다른 탭·다른 관리자가 바꾼 것(다른 항목·목록 판)을 줍기 위해서다. */
export function useCheckCredentialMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredentialCheckResponse, ApiError, string>({
    mutationFn: async (id) =>
      (await apiClient.post<AdminLlmCredentialCheckResponse>(`/admin/llm-credentials/${id}/check`)).data,
    onSuccess: (response) => {
      replaceCredential(queryClient, response.credential);
      void invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
