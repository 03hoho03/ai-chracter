import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminLlmCredentialListResponse, AdminLlmCredentialPoolRequest } from "../model/credential";
import { putList, reloadIfListStale } from "./cache";

/** 목록 사용 켜기·끄기. 끄기는 늘 되고(되돌리기 첫 단계), 켜기는 축마다 덮는 항목이 있어야 한다. 응답이 곧 새 목록이다. */
export function useSetPoolMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminLlmCredentialListResponse, ApiError, AdminLlmCredentialPoolRequest>({
    mutationFn: async (body) =>
      (await apiClient.put<AdminLlmCredentialListResponse>("/admin/llm-credentials/pool", body)).data,
    onSuccess: (list) => putList(queryClient, list),
    onError: (error) => reloadIfListStale(queryClient, error),
  });
}
