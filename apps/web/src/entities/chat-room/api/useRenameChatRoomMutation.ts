import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

// 단순 PATCH, 디바운스는 호출부(트리거 레벨)의 책임.
export function useRenameChatRoomMutation(roomId: string) {
  return useMutation<void, ApiError, string>({
    mutationFn: async (name) => {
      await apiClient.patch(`/chat-rooms/${roomId}`, { name });
    },
  });
}
