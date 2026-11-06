import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredentialListResponse, AdminLlmCredentialOrderRequest } from "../model/credential";
import { putList, reloadIfListStale } from "./cache";

/** 목록 전체의 새 순서. 판 번호와 `ids` 는 부르는 쪽이 누른 순간의 같은 목록에서 함께 만든다 — 새 판에 옛 순서를(또는 그 반대를) 섞어
 * 보내지 않게. 응답이 곧 새 목록(판 포함)이라 다시 받지 않고 넣는다. */
export function useReorderCredentialsMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredentialListResponse, ApiError, AdminLlmCredentialOrderRequest>({
    mutationFn: async (body) =>
      (await apiClient.put<AdminLlmCredentialListResponse>("/admin/llm-credentials/order", body)).data,
    onSuccess: (list) => putList(queryClient, list),
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
