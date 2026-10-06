import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { writeNovelChapterRevision, type NovelChapterResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type RestoreRevisionVariables = {
  novelId: string;
  chapterId: string;
  /** 되돌릴 옛 판. */
  revisionId: string;
  /** 되돌리기를 고를 때 지금 판이던 개정. 그사이 새 판이 생겼으면 서버가 409 로 막는다. */
  baseRevisionId: string;
};

/** `POST …/revisions/{revisionId}/restore` — 옛 판을 **새 판으로 복제**한다(201). 지금 판을 지우지 않으므로
 * 되돌린 것도 다시 되돌릴 수 있다. 응답이 장 전체라 그것으로 캐시를 바로 쓴다. */
export function useRestoreRevisionMutation() {
  const queryClient = useQueryClient();

  return useMutation<NovelChapterResponse, ApiError, RestoreRevisionVariables>({
    mutationFn: async ({ novelId, chapterId, revisionId, baseRevisionId }) =>
      (
        await apiClient.post<NovelChapterResponse>(
          `/novels/${novelId}/chapters/${chapterId}/revisions/${revisionId}/restore`,
          { baseRevisionId },
        )
      ).data,
    onSuccess: (chapter) => writeNovelChapterRevision(queryClient, chapter),
  });
}
