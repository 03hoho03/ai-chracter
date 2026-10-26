import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatRoomState } from "@/entities/chat-room";

/** 보내기의 낙관적 사용자 메시지를 방 캐시에서 뺀다. 클로버가 모자라 서버가 시작 전에 거절한 글은 서버에 없고 방의 입력
 * 초안이 맡으므로, 말풍선을 남기면 돌아와 다시 보낼 때 같은 글이 둘이 된다. 그사이 방을 다시 받아 그 메시지가 이미
 * 없으면 아무것도 바꾸지 않는다. */
export function removeOptimisticUserMessage(queryClient: QueryClient, roomId: string, messageId: string): void {
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
    if (!prev || !prev.messages.some((message) => message.id === messageId)) return prev;
    return { ...prev, messages: prev.messages.filter((message) => message.id !== messageId) };
  });
}
