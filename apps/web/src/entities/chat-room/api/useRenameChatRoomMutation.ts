import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

// 단순 PATCH, 디바운스는 호출부(트리거 레벨)의 책임. 내 방 목록이 방 이름을 보여 주므로 성공하면 무효화한다.
export function useRenameChatRoomMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (name) => {
      await apiClient.patch(`/chat-rooms/${roomId}`, { name });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
    },
  });
}
