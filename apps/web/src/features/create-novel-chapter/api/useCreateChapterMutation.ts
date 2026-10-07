import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelChapterModelId, NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type CreateChapterVariables = { novelId: string; endMessageId: string; expectedCost: number; model: NovelChapterModelId };

/** `POST /novels/{novelId}/chapters` — 고른 턴까지를 다음 화들로 쓰는 작업을 만든다(202). 몇 화로 나눌지는 서버가
 * 그 구간과 모델로 다시 센다. `expectedCost` 는 이용자가 확인한 그 후보의 금액이고, 서버가 다시 센 금액과 다르면
 * 차감 없이 409 다. `model` 은 그 화들을 쓸 모델로 늘 싣는다 — 허용 없는 상위 모델이면 403 이다. */
export function useCreateChapterMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, CreateChapterVariables>({
    mutationFn: async ({ novelId, endMessageId, expectedCost, model }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters`, { endMessageId, expectedCost, model }))
        .data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
