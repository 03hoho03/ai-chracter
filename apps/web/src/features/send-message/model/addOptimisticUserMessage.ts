import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

/** 보내기의 사용자 메시지를 방 캐시 끝에 먼저 둔다. 그 전에 진행 중인 방 조회를 끊는다 — 삭제·수정 뒤 다시 받는 조회가 늦게
 * 도착하면 서버의 옛 목록으로 방금 둔 말풍선을 지운다.
 *
 * 끊을 때 `revert: false` 다. 여기서 필요한 것은 늦게 올 조회 결과를 버리는 것뿐이고 캐시를 다른 시점 값으로 되돌릴 이유가
 * 없다. 기본값(`revert: true`)은 조회가 시작된 뒤의 캐시로 되돌리므로, 낙관적 반영과 취소의 순서가 바뀌면 방금 둔 것을
 * 지울 수 있다. */
export function addOptimisticUserMessage(queryClient: QueryClient, roomId: string, message: ChatMessage): void {
  void queryClient.cancelQueries({ queryKey: chatRoomKeys.detail(roomId) }, { revert: false });
  queryClient.setQueryData<ChatRoomState>(
    chatRoomKeys.detail(roomId),
    (prev) => prev && { ...prev, messages: [...prev.messages, message] },
  );
}
