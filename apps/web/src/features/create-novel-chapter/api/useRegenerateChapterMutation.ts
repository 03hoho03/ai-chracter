import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { NovelJobResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

import { onNovelChapterJobStarted } from "./onNovelChapterJobStarted";

type RegenerateChapterVariables = { novelId: string; chapterId: string; expectedCost: number };

/** `POST /novels/{novelId}/chapters/{chapterId}/regenerate` — 같은 대화 구간으로 그 장을 새로 쓰는 작업(202).
 * 마지막 장이 아니어도 되고, 결과는 그 장의 새 개정이라 지금 글은 이력에 남는다. */
export function useRegenerateChapterMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelJobResponse, ApiError, RegenerateChapterVariables>({
    mutationFn: async ({ novelId, chapterId, expectedCost }) =>
      (
        await apiClient.post<NovelJobResponse>(`/novels/${novelId}/chapters/${chapterId}/regenerate`, {
          expectedCost,
        })
      ).data,
    onSuccess: (job, { novelId }) => onNovelChapterJobStarted(queryClient, novelId, job),
  });
}
