import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { writeNovelChapterRevision, type NovelChapterResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type SaveChapterRevisionVariables = {
  novelId: string;
  chapterId: string;
  /** 고치기 시작할 때 보고 있던 개정. 그사이 다른 곳에서 새 개정이 생겼으면 서버가 409 로 막는다. */
  baseRevisionId: string;
  /** 장 전체 본문. 서버는 문단 범위를 모르므로 화면이 고른 범위를 바꿔 조립해 보낸다. */
  body: string;
};

/** `POST /novels/{novelId}/chapters/{chapterId}/revisions` — 직접 고친 본문을 새 개정으로 저장한다(201, 과금 없음).
 * 응답이 장 전체라 그것으로 캐시를 바로 쓴다. */
export function useSaveChapterRevisionMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, SaveChapterRevisionVariables>({
    mutationFn: async ({ novelId, chapterId, baseRevisionId, body }) =>
      (
        await apiClient.post<NovelChapterResponse>(`/novels/${novelId}/chapters/${chapterId}/revisions`, {
          baseRevisionId,
          body,
        })
      ).data,
    onSuccess: (chapter) => writeNovelChapterRevision(queryClient, chapter),
  });
}
