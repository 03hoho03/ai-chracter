import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type RegenerateChapterVariables = { novelId: string; chapterId: string; expectedCost: number; model: NovelChapterModelId };

/** `POST /novels/{novelId}/chapters/{chapterId}/regenerate` — 같은 대화 구간으로 그 장을 새로 쓰는 작업(202).
 * 마지막 장이 아니어도 되고, 결과는 그 장의 새 개정이라 지금 글은 이력에 남는다. 처음 만든 모델과 다른 모델을 골라도
 * 된다 — `model` 은 이번에 쓸 모델이고 `expectedCost` 는 그 모델의 재생성 가격이다. */
export function useRegenerateChapterMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, RegenerateChapterVariables>({
    mutationFn: async ({ novelId, chapterId, expectedCost, model }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters/${chapterId}/regenerate`, {
          expectedCost,
          model,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
