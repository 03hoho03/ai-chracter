import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

/** `POST`·`DELETE /webnovels/{novelId}/like` — 좋아요와 취소(둘 다 204, 이미 그 상태여도 204). 보낸 값을 캐시에 쓰는
 * 일은 연타를 묶는 호출부(`WebnovelLikeButton`)가 한다. */
export function useToggleWebnovelLikeMutation(novelId: string) {
  return useMutation<void, ApiError, boolean>({
    mutationFn: async (isLiked) => {
      if (isLiked) await apiClient.post(`/webnovels/${novelId}/like`);
      else await apiClient.delete(`/webnovels/${novelId}/like`);
    },
  });
}
