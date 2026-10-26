import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { promptRoutingKeys, type AdminPromptRoutingResponse } from "@/entities/prompt-routing";
import { apiClient } from "@/shared/lib/api/client";

import type { RoutingScope } from "../model/schema";
import { ROUTING_SAVE_PATHS } from "./routingPaths";

export type AdminPromptRoutingSaveRequest = components["schemas"]["AdminPromptRoutingSaveRequest"];

/** 그 범위(채팅 두 레인 또는 소설 레인)의 행을 갈아 끼운다. 응답이 새 해석이라 표 캐시에 그대로 넣고(표를 읽는 다른 화면도 같은 키라 함께 바뀐다) 이력 목록만
 * 다시 받는다. */
export function useSaveRoutingMutation(scope: RoutingScope) {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptRoutingResponse, ApiError, AdminPromptRoutingSaveRequest>({
    mutationFn: async (payload) =>
      (await apiClient.put<AdminPromptRoutingResponse>(ROUTING_SAVE_PATHS[scope], payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptRoutingKeys.table(), data);
      void queryClient.invalidateQueries({ queryKey: promptRoutingKeys.revisions() });
    },
  });
}
