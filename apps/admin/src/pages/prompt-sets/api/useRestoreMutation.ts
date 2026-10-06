import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { PromptLane } from "../model/lane";
import type { AdminPromptDraftResponse } from "../model/schema";
import { promptSetKeys } from "./keys";

/** 옛 버전을 초안으로 복제한다(= 롤백 경로) — 게시하지 않는 한 서비스에는 영향이 없다.
 * 응답이 새 초안 전체라 setQueryData로 바로 채우면 폼이 `values` prop을 통해 자연히 그
 * 내용으로 리셋된다. 서버는 원본 버전의 (레인, 모델) 체인 초안으로 넣는다 — 엔드포인트가 `{id}`만 받으므로
 * 캐시를 채울 자리 중 레인은 호출부가 알려 주고(`source.lane`), 모델은 응답의 `model`(= `source.model`)을 쓴다.
 * 호출부가 모델을 따로 넘기면 서버가 실제로 쓴 체인과 어긋날 여지가 생긴다. */
export function useRestoreMutation(lane: PromptLane) {
  const queryClient = useQueryClient();

  return useMutation<AdminPromptDraftResponse, ApiError, string>({
    mutationFn: async (id) =>
      (await apiClient.post<AdminPromptDraftResponse>(`/admin/prompt-sets/${id}/restore`)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(promptSetKeys.draft(lane, data.model), data);
      void queryClient.invalidateQueries({ queryKey: promptSetKeys.preview(lane, data.model) });
    },
  });
}
