import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "./types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

// techspec-chat-common.md §3 — 클라이언트가 임의로 상태를 비우지 않고, 서버 응답으로
// chatRoomKeys.detail(roomId) 캐시를 통째로 교체한다(서버가 최종 초기 상태의 단일 소스).
export function useResetChatRoomMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, void>({
    mutationFn: async () =>
      toChatRoomState((await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/reset`)).data),
    onSuccess: (room) => {
      queryClient.setQueryData(chatRoomKeys.detail(roomId), room);
    },
  });
}
