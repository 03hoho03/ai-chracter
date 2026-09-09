import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminPromptDraftResponse, AdminPromptDraftUpsertRequest } from "../model/schema";
import { promptSetKeys } from "./keys";

/** PUT .../draft는 섹션 전체 교체다(부분 패치가 아니다) — 응답이 이미 최신 전체 초안이라
 * invalidate 대신 setQueryData로 캐시를 바로 채운다(legal의 `useSaveDraftMutation`과 같은 모양).
 * 미리보기는 저장된 초안을 렌더하므로(요청 바디가 없다) 저장 직후엔 낡은 값이라 함께 무효화한다. */
export function useSaveDraftMutation() {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptDraftResponse, ApiError, AdminPromptDraftUpsertRequest>({
    mutationFn: async (payload) =>
      (await apiClient.put<AdminPromptDraftResponse>("/admin/prompt-sets/draft", payload)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptSetKeys.draft(), data);
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.preview() });
    },
  });
}
