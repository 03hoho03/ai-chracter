import type { ChatRoomState } from "./chatRoomState";

type RoomChatModel = Pick<ChatRoomState, "effectiveChatModel" | "effectiveChatModelName" | "turnCost">;

/** 방 상세 캐시에 다음 턴의 모델·그 이름·턴 가격 세 칸만 고쳐 쓴다. 모델을 바꾼 응답과, 클로버 429 뒤 방을 다시 받은
 * 값이 같은 칸을 고치므로 한 곳에 둔다 — 한쪽만 이름을 빠뜨리면 헤더의 모델 칩이 옛 이름으로 남는다.
 *
 * 메시지 등 나머지는 건드리지 않는다(시작 전에 거절된 낙관적 사용자 메시지는 서버에 없다). 캐시가 비어 있으면 그대로 둔다. */
export function applyRoomChatModel(prev: ChatRoomState | undefined, next: RoomChatModel): ChatRoomState | undefined {
  if (!prev) return prev;
  return {
    ...prev,
    effectiveChatModel: next.effectiveChatModel,
    effectiveChatModelName: next.effectiveChatModelName,
    turnCost: next.turnCost,
  };
}
