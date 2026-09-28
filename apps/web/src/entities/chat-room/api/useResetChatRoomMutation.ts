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
      // 초기화는 요약만 지우고 노트는 남긴다. remove가 아니라 invalidate인 이유: 열려 있는 기억 패널이 통째로
      // 불러오는 중으로 돌아가지 않게 하려는 것이다. 지운 요약이 리페치 전까지 캐시에 잠깐 남지만, 그 값으로
      // 저장하려 해도 서버의 버전 검사가 409로 막아 되살아나지 않는다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
    },
  });
}
