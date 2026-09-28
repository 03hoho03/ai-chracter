import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

export type ChatRoomMemory = components["schemas"]["ChatRoomMemoryResponse"];

// 방 상세와 따로 받는다 — 방 상세는 전송·재생성·포커스 복귀로 자주 다시 받는데, 기억 편집 폼의 기준값이
// 그때마다 흔들릴 이유가 없다. 패널이 열려 있을 때만 조회한다.
export function useChatRoomMemoryQuery(roomId: string, enabled: boolean) {
  return useQuery<ChatRoomMemory, ApiError>({
    queryKey: chatRoomKeys.memory(roomId),
    queryFn: async () => (await apiClient.get<ChatRoomMemory>(`/chat-rooms/${roomId}/memory`)).data,
    enabled,
  });
}
