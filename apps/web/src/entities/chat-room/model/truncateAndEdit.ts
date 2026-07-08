import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "../api/keys";
import type { ChatRoomState } from "../api/types";

// techspec-chat-common.md §2.1, US-023/077 — 사용자 메시지 수정은 그 메시지 이후 메시지를 전부
// 잘라내고 내용만 갱신하는 낙관적 반영이다(별도 분기 조회/전환 UI 없음). 실제 재전송(PATCH
// .../messages/{id} SSE)은 호출부(useSendMessage)가 이어서 처리한다 — 이 함수는 캐시 절단만 담당한다.
export function truncateAndEdit(
  queryClient: QueryClient,
  roomId: string,
  messageId: string,
  newContent: string,
): void {
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
    if (!prev) return prev;
    const index = prev.messages.findIndex((message) => message.id === messageId);
    if (index === -1) return prev;

    const messages = prev.messages
      .slice(0, index + 1)
      .map((message, i) => (i === index ? { ...message, content: newContent } : message));
    return { ...prev, messages };
  });
}
