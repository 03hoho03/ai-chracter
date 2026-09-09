import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminPromptDraftResponse } from "../model/schema";
import { promptSetKeys } from "./keys";

/** 옛 버전을 초안으로 복제한다(= 롤백 경로) — 게시하지 않는 한 서비스에는 영향이 없다.
 * 응답이 새 초안 전체라 setQueryData로 바로 채우면 폼이 `values` prop을 통해 자연히 그
 * 내용으로 리셋된다. */
export function useRestoreMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptDraftResponse, ApiError, string>({
    mutationFn: async (id) =>
      (await apiClient.post<AdminPromptDraftResponse>(`/admin/prompt-sets/${id}/restore`)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptSetKeys.draft(), data);
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.preview() });
    },
  });
}
