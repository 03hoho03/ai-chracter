import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type CreateOutlineVariables = { novelId: string; expectedCost: number; model: NovelChapterModelId };

/** `POST /novels/{novelId}/outline` — 지금 승인한 담을 대화로 전체 구성안을 만드는 작업(202). 금액은 고른 모델의 구성안 고정가이고
 * `expectedCost` 는 구성안 조회의 그 모델 금액이다. 끝나면 새 구성안이 미승인 초안으로 온다. */
export function useCreateOutlineMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, CreateOutlineVariables>({
    mutationFn: async ({ novelId, expectedCost, model }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/outline`, { expectedCost, model })).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
