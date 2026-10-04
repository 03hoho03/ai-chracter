import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";

// 사용자 메시지 수정은 그 메시지 이후 메시지를 전부
// 잘라내고 내용만 갱신하는 낙관적 반영이다(별도 분기 조회/전환 UI 없음). 실제 재전송(PATCH
// .../messages/{id} SSE)은 호출부(useSendMessage)가 이어서 처리한다 — 이 함수는 캐시 절단만 담당한다.
// 반환값은 자르기 전 목록이다(바꾼 것이 없으면 undefined). 서버가 수정을 시작도 하지 않고 거절하면 호출부가
// 이 값으로 `restoreMessages`를 불러 화면을 되돌린다.
export function truncateAndEdit(
  queryClient: QueryClient,
  roomId: string,
  messageId: string,
  newContent: string,
): ChatMessage[] | undefined {
  const prev = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId));
  if (!prev) return undefined;
  const index = prev.messages.findIndex((message) => message.id === messageId);
  if (index === -1) return undefined;

  const messages = prev.messages
    .slice(0, index + 1)
    .map((message, i) => (i === index ? { ...message, content: newContent } : message));
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), { ...prev, messages });
  return prev.messages;
}

/** `truncateAndEdit`가 돌려준 자르기 전 목록을 그대로 다시 넣는다. */
export function restoreMessages(queryClient: QueryClient, roomId: string, messages: ChatMessage[]): void {
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => prev && { ...prev, messages });
}
