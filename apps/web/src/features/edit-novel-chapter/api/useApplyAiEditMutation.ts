import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { writeNovelChapterRevision, type NovelChapterResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type ApplyAiEditVariables = { novelId: string; jobId: string };

/** `POST /novels/{novelId}/jobs/{jobId}/apply` — AI 수정안을 그 장의 새 개정으로 만든다(201, 추가 과금 없음).
 * 서버가 그 장의 다른 미적용 수정안을 함께 비우므로, 캐시 쓰기도 그 장의 수정안을 모두 뺀다. */
export function useApplyAiEditMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, ApplyAiEditVariables>({
    mutationFn: async ({ novelId, jobId }) =>
      (await apiClient.post<NovelChapterResponse>(`/novels/${novelId}/jobs/${jobId}/apply`)).data,
    onSuccess: (chapter) => writeNovelChapterRevision(queryClient, chapter),
  });
}
