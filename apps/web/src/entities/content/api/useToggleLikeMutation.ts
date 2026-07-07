import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

/** techspec-content-detail.md §4 — 응답 바디를 읽지 않는 낙관적 토글이라 mutationFn은 void를 반환한다.
 * 실제 낙관적 반영/디바운스/롤백은 호출부(ContentDetailView)가 담당한다. */
export function useToggleLikeMutation(contentId: string) {
  return useMutation<void, ApiError, boolean>({
    mutationFn: async (liked) => {
      if (liked) {
        await apiClient.post(`/contents/${contentId}/like`);
      } else {
        await apiClient.delete(`/contents/${contentId}/like`);
      }
    },
  });
}
