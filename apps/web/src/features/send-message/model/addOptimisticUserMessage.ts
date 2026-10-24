import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

import { cancelRoomRefetch } from "./cancelRoomRefetch";

/** 보내기의 사용자 메시지를 방 캐시 끝에 먼저 둔다. 진행 중인 방 조회를 먼저 끊는다(`cancelRoomRefetch`). */
export function addOptimisticUserMessage(queryClient: QueryClient, roomId: string, message: ChatMessage): void {
  cancelRoomRefetch(queryClient, roomId);
  queryClient.setQueryData<ChatRoomState>(
    chatRoomKeys.detail(roomId),
    (prev) => prev && { ...prev, messages: [...prev.messages, message] },
  );
}
