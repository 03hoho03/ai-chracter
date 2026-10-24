import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { promptRoutingKeys, type AdminPromptRoutingResponse } from "@/entities/prompt-routing";
import { apiClient } from "@/shared/lib/api/client";

export type AdminPromptRoutingSaveRequest = components["schemas"]["AdminPromptRoutingSaveRequest"];

/** 표 전체를 갈아 끼운다. 응답이 새 해석이라 표 캐시에 그대로 넣고(표를 읽는 다른 화면도 같은 키라 함께 바뀐다) 이력 목록만
 * 다시 받는다. */
export function useSaveRoutingMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptRoutingResponse, ApiError, AdminPromptRoutingSaveRequest>({
    mutationFn: async (payload) =>
      (await apiClient.put<AdminPromptRoutingResponse>("/admin/prompt-routing", payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptRoutingKeys.table(), data);
      void queryClient.invalidateQueries({ queryKey: promptRoutingKeys.revisions() });
    },
  });
}
