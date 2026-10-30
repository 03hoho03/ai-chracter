import type { ChatModel } from "@/entities/chat-model";
import type { ChatRoomState } from "@/entities/chat-room";

/** 방에 저장한 모델을 지금 쓸 수 없어 서버가 그 방을 기본 모델로 돌리고 있을 때 모델 모달에 띄우는 문장. 모델을 공개
 * 목록에서 빼면 그 모델을 저장한 방은 다음 턴부터 기본 모델·기본 가격으로 도는데, 헤더 칩은 실제로 쓰는 모델 이름만 보여
 * 주므로 이 문장이 없으면 고른 적 없는 모델로 바뀐 이유를 알 길이 없다. 숨긴 모델 이름은 목록에 없어 말하지 않고, 판정이
 * 계정을 보지 않아 계정 탓으로 말하지 않는다. */
export const ROOM_CHAT_MODEL_FALLBACK_NOTICE = "이 대화방에서 고른 모델을 지금은 쓸 수 없어 기본 모델로 대화하고 있어요.";

/** 저장한 모델이 있고 그것이 서버가 정한 실제 모델과 다를 때만 안내한다. 저장한 적 없는 방(기본 모델)이나 저장한 모델
 * 그대로 도는 방에는 띄우지 않는다. */
export function roomChatModelNotice(room: Pick<ChatRoomState, "chatModel" | "effectiveChatModel">): string | undefined {
  if (room.chatModel === undefined || room.chatModel === room.effectiveChatModel) return undefined;
  return ROOM_CHAT_MODEL_FALLBACK_NOTICE;
}

/** 방 상세가 들고 있는 실제 모델이 받은 모델 목록에 없는가. 화면을 띄워 둔 사이 운영자가 모델을 목록에서 빼면 캐시의
 * 실제 모델은 옛 값으로 남는다 — 서버는 이미 그 방을 기본 모델로 돌린다. 참이면 방 상세를 새로 받아 칩·가격·안내를 서버
 * 값에 맞춘다. */
export function isRoomModelMissingFromList(models: readonly Pick<ChatModel, "id">[], effectiveChatModel: string): boolean {
  return !models.some((model) => model.id === effectiveChatModel);
}
