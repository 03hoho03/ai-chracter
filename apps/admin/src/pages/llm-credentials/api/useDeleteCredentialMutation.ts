import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { dropCredential, invalidateCredentials, reloadIfListStale } from "./cache";

/** 지운다(확인 기록도 함께). 목록 판이 올랐는데 응답이 비어 있어(204) 목록을 다시 받고, 추가와 같은 이유로 그 재조회가 끝날 때까지
 * 진행 중으로 둔다.
 * 오프라인이면 일시정지하지 않고 바로 실패한다(`networkMode: "always"`) — 멈춘 채 닫히지 않거나 연결이 돌아온 순간 모르게 보내지 않게. */
export function useDeleteCredentialMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, string>({
    mutationFn: async (id) => {
      await apiClient.delete(`/admin/llm-credentials/${id}`);
    },
    networkMode: "always",
    onSuccess: (_data, id) => {
      dropCredential(queryClient, id);
      return invalidateCredentials(queryClient);
    },
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
