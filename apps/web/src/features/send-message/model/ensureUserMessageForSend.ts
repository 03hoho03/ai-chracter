import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState, ChatStreamRequest } from "@/entities/chat-room";

/** 다시 보내기 직전에 부른다. 보내기 요청이면 그 글의 사용자 메시지가 목록 끝에 있게 하고, 이미 있으면 두지 않는다.
 * 시작 전에 거절된 메시지는 서버에 없으므로, 거절과 다시 보내기 사이에 탭 복귀 등으로 방을 재조회하면 낙관적 메시지가
 * 캐시에서 사라진다. 그대로 다시 보내면 응답만 붙고 내 말풍선은 새로고침 전까지 보이지 않는다. 수정·재생성은 새 사용자
 * 메시지를 만들지 않으므로 손대지 않는다. */
export function ensureUserMessageForSend(queryClient: QueryClient, roomId: string, payload: ChatStreamRequest): void {
  if (payload.kind !== "send") return;
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
    if (!prev) return prev;
    const tail = prev.messages.at(-1);
    if (tail?.role === "user" && tail.content === payload.content) return prev;
    const optimisticMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: payload.content,
      createdAt: new Date().toISOString(),
    };
    return { ...prev, messages: [...prev.messages, optimisticMessage] };
  });
}
