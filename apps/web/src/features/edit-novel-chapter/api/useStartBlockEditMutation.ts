import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { novelKeys, type NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type StartBlockEditVariables = {
  novelId: string;
  chapterId: string;
  baseRevisionId: string;
  /** 고친 블록 id(본문 차례, 같은 장면 안). */
  blockIds: string[];
  instruction: string;
  /** 이용자가 확인한 금액. 서버 단가와 다르면 차감 없이 409 다. */
  expectedCost: number;
};

/** `POST /novels/{novelId}/chapters/{chapterId}/block-edits` — 고른 블록마다 수정안을 만드는 작업(202, 블록 수와 상관없이 AI 수정
 * 단가 한 번). 결과는 블록별 수정안으로 상세에 실리고, 이용자가 단위마다 적용하거나 버린다.
 *
 * 시작 뒤 캐시 정리는 옛 연속 범위 요청과 같다: 202 응답으로 작업 캐시를 채우고, 상세(진행 중 작업)와 잔액을 낡음으로 표시한다. */
export function useStartBlockEditMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, StartBlockEditVariables>({
    mutationFn: async ({ novelId, chapterId, ...body }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters/${chapterId}/block-edits`, body)).data,
    onSuccess: (job, { novelId }) => {
      queryClient.setQueryData(novelKeys.job(novelId, job.id), job);
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.all });
    },
  });
}
