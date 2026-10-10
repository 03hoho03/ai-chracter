import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

// 콘텐츠 스코프 목록 invalidate/현재 보고 있던 방이면 목록으로 navigate하는 책임은
// 호출부(widgets/chat-room-list)에 있다. 내 방 목록(전체·최근)은 어느 화면에서 지워도 함께 갱신돼야 해 여기서 무효화한다.
export function useDeleteChatRoomMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await apiClient.delete(`/chat-rooms/${roomId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
    },
  });
}
