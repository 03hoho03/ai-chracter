import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { promptRoutingKeys, type AdminPromptRoutingResponse } from "@/entities/prompt-routing";
import { apiClient } from "@/shared/lib/api/client";

export type AdminPromptRoutingRestoreRequest = components["schemas"]["AdminPromptRoutingRestoreRequest"];

type RestoreVariables = { id: string } & AdminPromptRoutingRestoreRequest;

/** 옛 이력의 표를 지금 env·게시 세트로 다시 검사해 새 이력으로 저장한다 — 캐시 처리는 저장과 같다. */
export function useRestoreRoutingMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptRoutingResponse, ApiError, RestoreVariables>({
    mutationFn: async ({ id, ...payload }) =>
      (await apiClient.post<AdminPromptRoutingResponse>(`/admin/prompt-routing/revisions/${id}/restore`, payload))
        .data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptRoutingKeys.table(), data);
      void queryClient.invalidateQueries({ queryKey: promptRoutingKeys.revisions() });
    },
  });
}
