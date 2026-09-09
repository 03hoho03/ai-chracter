import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { promptSetKeys } from "./keys";

export type AdminPromptPublishRequest = components["schemas"]["AdminPromptPublishRequest"];
export type AdminPromptSetDetailResponse = components["schemas"]["AdminPromptSetDetailResponse"];

/** 게시는 저장된 초안을 새 버전으로 복제할 뿐 초안 자체는 그대로 남는다(legal과 같다, §K) —
 * 그래서 초안 캐시는 건드리지 않고 버전 목록·미리보기만 무효화한다. */
export function usePublishMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptSetDetailResponse, ApiError, AdminPromptPublishRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminPromptSetDetailResponse>("/admin/prompt-sets/publish", payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.list() });
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.preview() });
    },
  });
}
