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
      // 초기화는 요약을 지운다(노트는 남는다) — 캐시의 기억은 낡은 게 아니라 틀린 값이 되므로 invalidate로
      // 남기지 않고 버린다. 다음에 기억 패널을 열면 새로 받는다. 기억 패널이 열려 있는 채 초기화되면 다음
      // 렌더에서 불러오는 중으로 돌아가 폼을 새로 만들므로, 저장하지 않은 노트 입력은 사라진다.
      queryClient.removeQueries({ queryKey: chatRoomKeys.memory(roomId) });
    },
  });
}
