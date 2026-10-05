import type { ChatMessage } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";

/** 긴 방에 들어갈 때 받는 최근 메시지 수이자 위로 불러오기 한 번에 더 받는 수(약 25턴). */
export const CHAT_ROOM_MESSAGE_PAGE_SIZE = 50;

/**
 * 방 상세를 서버에서 다시 받을 때 몇 개를 받을까 — 화면이 이미 들고 있는 깊이를 줄이지 않는다. 탭 복귀 재조회나
 * 버전 고정 응답이 캐시를 통째로 바꾸므로, 꼬리 창 크기만 받으면 사용자가 위로 불러 둔 메시지가 그때마다 사라진다.
 */
export function chatRoomMessageLimit(cached: ChatRoomState | undefined): number {
  return Math.max(CHAT_ROOM_MESSAGE_PAGE_SIZE, cached?.messages.length ?? 0);
}

export type OlderMessagesPage = { messages: ChatMessage[]; hasMoreBefore: boolean };

/**
 * 위로 불러온 페이지를 캐시 앞에 붙인다. 요청할 때의 커서가 지금도 캐시의 첫 메시지일 때만 붙인다 — 그사이 재조회가
 * 캐시를 바꿨으면 이 페이지와 지금 첫 메시지 사이가 이어진다는 보장이 없어(틈이 생길 수 있다) 버리고, 앞에 더 있다는
 * 표시는 그대로라 다시 누르면 이어 받는다. 이미 있는 id 는 다시 넣지 않는다.
 */
export function prependOlderMessages(
  prev: ChatRoomState | undefined,
  page: OlderMessagesPage,
  cursorId: string,
): ChatRoomState | undefined {
  if (!prev || prev.messages[0]?.id !== cursorId) return prev;
  const loadedIds = new Set(prev.messages.map((message) => message.id));
  const older = page.messages.filter((message) => !loadedIds.has(message.id));
  return { ...prev, messages: [...older, ...prev.messages], hasMoreMessagesBefore: page.hasMoreBefore };
}
