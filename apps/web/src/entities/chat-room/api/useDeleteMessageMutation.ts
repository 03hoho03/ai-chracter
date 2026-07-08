import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "./types";

// US-077 — 삭제는 204라 서버가 갱신된 목록을 돌려주지 않는다. useResetChatRoomMutation(서버가
// 통째로 교체)과 달리, 여기서는 성공한 messageId만큼 캐시에서 직접 filter로 제거한다.
export function useDeleteMessageMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (messageId) => {
      await apiClient.delete(`/chat-rooms/${roomId}/messages/${messageId}`);
    },
    onSuccess: (_data, messageId) => {
      queryClient.setQueryData<ChatRoomState>(
        chatRoomKeys.detail(roomId),
        (prev) => prev && { ...prev, messages: prev.messages.filter((message) => message.id !== messageId) },
      );
    },
  });
}
