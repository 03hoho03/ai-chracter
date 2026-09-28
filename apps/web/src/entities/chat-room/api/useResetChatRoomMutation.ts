import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

// 클라이언트가 임의로 상태를 비우지 않고, 서버 응답으로
// chatRoomKeys.detail(roomId) 캐시를 통째로 교체한다(서버가 최종 초기 상태의 단일 소스).
export function useResetChatRoomMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, void>({
    mutationFn: async () =>
      toChatRoomState((await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/reset`)).data),
    onSuccess: (room) => {
      queryClient.setQueryData(chatRoomKeys.detail(roomId), room);
      // 초기화는 요약만 지우고 노트는 남긴다 — 버린 값이 아니라 낡은 값이라 remove가 아니라 invalidate다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
    },
  });
}
