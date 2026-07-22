import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import type { ChatRoomState } from "./chat-room";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];
type ChatRoomCreateRequestDto = components["schemas"]["ChatRoomCreateRequest"];

// techspec-chat-common.md §3 — "새 대화 시작"(플레이 버튼의 최초 진입 포함)의 실체. 캐릭터/스토리
// 공용(BE의 ChatRoomCreateRequest.contentType은 US-057부터 "character"|"story" 둘 다 허용).
export function useStartChatMutation() {
  return useMutation<ChatRoomState, ApiError, ChatRoomCreateRequestDto>({
    mutationFn: async (payload) =>
      toChatRoomState((await apiClient.post<ChatRoomResponseDto>("/chat-rooms", payload)).data),
  });
}
