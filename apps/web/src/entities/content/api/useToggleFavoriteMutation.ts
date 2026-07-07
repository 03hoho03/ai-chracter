import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

/** techspec-content-detail.md §4 — 좋아요 토글(useToggleLikeMutation)과 동일하게 응답 바디를 읽지 않는
 * 낙관적 토글이라 mutationFn은 void를 반환한다. 낙관적 반영/디바운스/롤백은 호출부(ContentDetailView)가 담당한다. */
export function useToggleFavoriteMutation(contentId: string) {
  return useMutation<void, ApiError, boolean>({
    mutationFn: async (favorited) => {
      if (favorited) {
        await apiClient.post(`/contents/${contentId}/favorite`);
      } else {
        await apiClient.delete(`/contents/${contentId}/favorite`);
      }
    },
  });
}
