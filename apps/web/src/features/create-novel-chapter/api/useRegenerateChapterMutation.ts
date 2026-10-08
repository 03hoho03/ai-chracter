import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type RegenerateChapterVariables = { novelId: string; batchId: string; expectedCost: number; model: NovelChapterModelId };

/** `POST /novels/{novelId}/batches/{batchId}/regenerate` — 한 번에 만든 화들(묶음)을 같은 대화 구간·같은 화 수로
 * 새로 쓰는 작업(202). 마지막 묶음이 아니어도 되고, 결과는 화마다 새 개정이라 지금 글은 이력에 남는다. 처음 만든
 * 모델과 다른 모델을 골라도 되지만 그 묶음을 담지 못하는 모델은 409 다. `expectedCost` 는 상세의 묶음 다시 만들기
 * 목록에서 고른 모델의 금액이다. */
export function useRegenerateChapterMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, RegenerateChapterVariables>({
    mutationFn: async ({ novelId, batchId, expectedCost, model }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/batches/${batchId}/regenerate`, {
          expectedCost,
          model,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
