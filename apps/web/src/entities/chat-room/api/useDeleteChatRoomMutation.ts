import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

// US-049(원본 PRD 번호) — 삭제 후 목록 invalidate/현재 보고 있던 방이면 목록으로 navigate하는 책임은
// 호출부(widgets/chat-room-list)에 있다. 이 훅은 삭제 요청만 담당한다.
export function useDeleteChatRoomMutation(roomId: string) {
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.delete(`/chat-rooms/${roomId}`);
    },
  });
}
