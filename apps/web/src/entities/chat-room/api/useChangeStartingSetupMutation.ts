import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import type { ChatRoomState } from "./types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChangeStartingSetupRequestDto = components["schemas"]["ChangeStartingSetupRequest"];

// US-080/081, techspec-chat-story.md §6 — 기존 방은 그대로 두고 새 방을 만들어 반환하므로,
// useStartChatMutation과 동일하게 캐시 조작 없음(호출부가 응답의 새 room.id로 navigate한다).
export function useChangeStartingSetupMutation(roomId: string) {
  return useMutation<ChatRoomState, ApiError, ChangeStartingSetupRequestDto>({
    mutationFn: async (payload) =>
      toChatRoomState(
        (await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/change-starting-setup`, payload)).data,
      ),
  });
}
