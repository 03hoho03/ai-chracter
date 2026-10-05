import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";
import { chatRoomMessageLimit } from "../model/messagePaging";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

/** 방 상세를 받는다. 받는 메시지 수는 캐시가 이미 들고 있는 깊이 이상이다(`chatRoomMessageLimit`) — 탭 복귀 재조회가
 * 위로 불러 둔 메시지를 자르지 않는다. */
export async function fetchChatRoom(queryClient: QueryClient, roomId: string): Promise<ChatRoomState> {
  const messageLimit = chatRoomMessageLimit(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId)));
  return toChatRoomState(
    (await apiClient.get<ChatRoomResponseDto>(`/chat-rooms/${roomId}`, { params: { messageLimit } })).data,
  );
}

// applyStreamEvent/useSendMessage가 이미 이 캐시 키를 ChatRoomState 모양으로
// setQueryData하고 있으므로, 최초 조회도 같은 모양으로 저장해야 SSE 이벤트가 이어서 반영된다.
export function useChatRoomQuery(roomId: string) {
  const queryClient = useQueryClient();
  return useQuery<ChatRoomState, ApiError>({
    queryKey: chatRoomKeys.detail(roomId),
    queryFn: () => fetchChatRoom(queryClient, roomId),
  });
}
