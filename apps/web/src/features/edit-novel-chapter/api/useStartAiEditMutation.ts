import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { novelKeys, type NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type StartAiEditVariables = {
  novelId: string;
  chapterId: string;
  baseRevisionId: string;
  paragraphStart: number;
  paragraphEnd: number;
  instruction: string;
  /** 이용자가 확인한 금액. 서버 단가와 다르면 차감 없이 409 다. */
  expectedCost: number;
};

/** `POST /novels/{novelId}/chapters/{chapterId}/ai-edits` — 고른 문단을 지시대로 고친 수정안을 만드는 작업(202).
 * 결과는 바로 개정이 되지 않고 수정안으로 남아, 이용자가 적용하거나 버린다.
 *
 * 시작 뒤에 늘 일어나야 할 캐시 정리를 여기 둔다: 202 응답으로 작업 캐시를 미리 채우고(폴링 첫 응답 전에도
 * 진행 중을 그린다), 상세는 진행 중 작업이 생겨 낡았고(다른 버튼을 잠근다), 잔액은 이미 차감돼 낡았다. */
export function useStartAiEditMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, StartAiEditVariables>({
    mutationFn: async ({ novelId, chapterId, ...body }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters/${chapterId}/ai-edits`, body)).data,
    onSuccess: (job, { novelId }) => {
      queryClient.setQueryData(novelKeys.job(novelId, job.id), job);
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.all });
    },
  });
}
