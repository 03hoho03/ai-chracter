import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type DeleteLastChapterVariables = { novelId: string; batchId: string };

/** `DELETE /novels/{novelId}/batches/{batchId}` — 마지막에 한 번에 만든 화들(마지막 묶음)을 함께 지운다(204, 과금
 * 없음). 다음 화는 그 화들이 시작한 대화부터 다시 만든다. 캐시 정리는 순서가 있어(상세를 먼저 받아 화면이 그 화들을
 * 떠난 뒤 화 캐시를 버린다) 호출부 모달이 한다. */
export function useDeleteLastChapterMutation() {
  return useMutation<void, ApiError, DeleteLastChapterVariables>({
    mutationFn: async ({ novelId, batchId }) => {
      await apiClient.delete(`/novels/${novelId}/batches/${batchId}`);
    },
  });
}
