import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

// prd-image-library US-006 — 삭제 후 목록 invalidate/토스트/409 사용처 재표시 책임은
// 호출부(pages/studio-images)에 있다. 이 훅은 삭제 요청만 담당한다(useDeleteChatRoomMutation과
// 동일 구조). 사용 중인 이미지는 서버가 409에 detail.usages를 담아 거부한다.
export function useDeleteGeneratedImageMutation(assetId: string) {
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.delete(`/me/generated-images/${assetId}`);
    },
  });
}
