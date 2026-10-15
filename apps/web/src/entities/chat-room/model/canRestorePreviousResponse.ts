import type { ChatMessage } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";

/** 이 메시지의 메뉴에 "방금 전 답변으로"를 둘 것인가. 서버가 되돌릴 수 있다고 알려 준 AI 응답이 지금도 마지막 메시지일 때만
 * 둔다 — 서버의 거절 조건(보관을 밀어낸 응답이 방의 마지막 메시지인가)과 같은 비교다. 마지막인지도 보는 이유는 보내기가
 * 실패하면 방을 다시 받지 않아서다: 서버는 보내기를 받으며 보관을 지웠는데, 화면에는 그 뒤에 붙은 사용자 메시지와 옛
 * 표시가 함께 남는다. */
export function canRestorePreviousResponse(
  room: Pick<ChatRoomState, "previousResponseFor" | "messages">,
  message: Pick<ChatMessage, "id" | "role">,
): boolean {
  return (
    message.role === "assistant" &&
    room.previousResponseFor === message.id &&
    room.messages.at(-1)?.id === message.id
  );
}
