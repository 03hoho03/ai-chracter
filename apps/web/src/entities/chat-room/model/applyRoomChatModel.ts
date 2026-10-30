import type { ChatRoomState } from "./chatRoomState";

/** 모델을 바꾼 응답의 저장 모델은 null 일 수 있다(기본 모델) — 방 상태에서는 undefined 로 접는다. */
type RoomChatModel = Pick<ChatRoomState, "effectiveChatModel" | "effectiveChatModelName" | "turnCost"> & {
  chatModel?: string | null;
};

/** 방 상세 캐시에 저장한 모델과 다음 턴의 모델·그 이름·턴 가격 네 칸만 고쳐 쓴다. 모델을 바꾼 응답과, 클로버 429 뒤 방을
 * 다시 받은 값이 같은 칸을 고치므로 한 곳에 둔다 — 한쪽만 이름을 빠뜨리면 헤더의 모델 칩이 옛 이름으로 남고, 저장한 모델을
 * 빠뜨리면 모델 모달이 이미 고친 방에 "고른 모델을 쓸 수 없다"는 안내를 계속 띄운다.
 *
 * 메시지 등 나머지는 건드리지 않는다(시작 전에 거절된 낙관적 사용자 메시지는 서버에 없다). 캐시가 비어 있으면 그대로 둔다. */
export function applyRoomChatModel(prev: ChatRoomState | undefined, next: RoomChatModel): ChatRoomState | undefined {
  if (!prev) return prev;
  return {
    ...prev,
    chatModel: next.chatModel ?? undefined,
    effectiveChatModel: next.effectiveChatModel,
    effectiveChatModelName: next.effectiveChatModelName,
    turnCost: next.turnCost,
  };
}
