import type { ChatRoomState } from "./chatRoomState";

/** 지운 메시지를 방 상태에서 뺀다. 삭제 응답에는 방이 없으므로 캐시를 직접 고친다.
 * 되돌릴 답 표시(`previousResponseFor`)도 함께 비운다 — 서버는 어느 메시지를 지워도 보관해 둔 직전 응답을 지운다. 지운 것이
 * 앞쪽 메시지면 재생성한 응답이 여전히 마지막이라, 표시를 남기면 누를 때마다 거절될 "방금 전 답변으로"가 메뉴에 남는다. */
export function removeDeletedMessage(room: ChatRoomState, messageId: string): ChatRoomState {
  return {
    ...room,
    messages: room.messages.filter((message) => message.id !== messageId),
    previousResponseFor: undefined,
  };
}
