import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";

// techspec-chat-common.md §3 — 단순 PATCH, 디바운스는 호출부(트리거 레벨)의 책임(techspec-overview.md §11).
export function useRenameChatRoomMutation(roomId: string) {
  return useMutation<void, ApiError, string>({
    mutationFn: async (name) => {
      await apiClient.patch(`/chat-rooms/${roomId}`, { name });
    },
  });
}
