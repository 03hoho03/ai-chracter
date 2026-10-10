import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChangeStartingSetupRequestDto = components["schemas"]["ChangeStartingSetupRequest"];

// 기존 방은 그대로 두고 새 방을 만들어 반환한다(호출부가 응답의 새 room.id로 navigate한다).
// useStartChatMutation과 같은 이유로 내 방 목록만 무효화한다.
export function useChangeStartingSetupMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, ChangeStartingSetupRequestDto>({
    mutationFn: async (payload) =>
      toChatRoomState(
        (await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/change-starting-setup`, payload)).data,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
    },
  });
}
