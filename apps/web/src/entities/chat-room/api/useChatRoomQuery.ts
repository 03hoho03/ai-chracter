import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "./types";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

// US-055 — applyStreamEvent/useSendMessage(US-052/054)가 이미 이 캐시 키를 ChatRoomState 모양으로
// setQueryData하고 있으므로, 최초 조회도 같은 모양으로 저장해야 SSE 이벤트가 이어서 반영된다.
export function useChatRoomQuery(roomId: string) {
  return useQuery<ChatRoomState, ApiError>({
    queryKey: chatRoomKeys.detail(roomId),
    queryFn: async () =>
      toChatRoomState((await apiClient.get<ChatRoomResponseDto>(`/chat-rooms/${roomId}`)).data),
  });
}
