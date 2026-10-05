import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type CreateChapterVariables = { novelId: string; endMessageId: string; expectedCost: number };

/** `POST /novels/{novelId}/chapters` — 고른 턴까지를 다음 장으로 쓰는 작업을 만든다(202). `expectedCost` 는
 * 이용자가 확인한 금액이고, 서버 단가와 다르면 차감 없이 409 다. */
export function useCreateChapterMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, CreateChapterVariables>({
    mutationFn: async ({ novelId, endMessageId, expectedCost }) =>
      (await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters`, { endMessageId, expectedCost })).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
