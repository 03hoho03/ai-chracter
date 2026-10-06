import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { novelKeys, type NovelDetailResponse } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

type DismissAiEditVariables = { novelId: string; jobId: string };

/** `POST /novels/{novelId}/jobs/{jobId}/dismiss` — AI 수정안을 버린다(204). 쓴 클로버는 돌아오지 않는다. 응답에
 * 본문이 없어 상세의 미적용 목록에서 그 수정안을 바로 빼고, 서버 값으로 다시 받게 표시한다. */
export function useDismissAiEditMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, DismissAiEditVariables>({
    mutationFn: async ({ novelId, jobId }) => {
      await apiClient.post(`/novels/${novelId}/jobs/${jobId}/dismiss`);
    },
    onSuccess: (_, { novelId, jobId }) => {
      queryClient.setQueryData<NovelDetailResponse>(novelKeys.detail(novelId), (novel) =>
        novel === undefined
          ? undefined
          : { ...novel, pendingAiEdits: novel.pendingAiEdits.filter((edit) => edit.id !== jobId) },
      );
      void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
    },
  });
}
