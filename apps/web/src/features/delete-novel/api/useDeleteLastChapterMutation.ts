import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

type DeleteLastChapterVariables = { novelId: string; chapterId: string };

/** `DELETE /novels/{novelId}/chapters/{chapterId}` — 마지막 장을 지운다(204, 과금 없음). 다음 장은 이 장이 시작한
 * 대화부터 다시 만든다. 캐시 정리는 순서가 있어(상세를 먼저 받아 화면이 그 장을 떠난 뒤 장 캐시를 버린다)
 * 호출부 모달이 한다. */
export function useDeleteLastChapterMutation() {
  return useMutation<void, ApiError, DeleteLastChapterVariables>({
    mutationFn: async ({ novelId, chapterId }) => {
      await apiClient.delete(`/novels/${novelId}/chapters/${chapterId}`);
    },
  });
}
