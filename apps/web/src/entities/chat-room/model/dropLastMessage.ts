import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";

/** 재생성 클릭 즉시 옛 답변을 화면에서 지운다.
 * 반환값이 곧 "복원해야 할 것"이다(호출부는 이 값의 유무로 복원 여부를 판단한다).
 * 마지막이 assistant 일 때만 지운다. 재생성 버튼은 마지막이
 * assistant 일 때만 뜨지만(ChatRoomView.tsx:173-174), retry()가 같은 payload로 다시 들어올 때
 * 캐시는 그 사이 재조회로 바뀌어 있을 수 있다. */
export function dropLastMessage(queryClient: QueryClient, roomId: string): ChatMessage | undefined {
  const prev = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId));
  const last = prev?.messages.at(-1);
  if (!prev || last?.role !== "assistant") return undefined;

  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), {
    ...prev,
    messages: prev.messages.slice(0, -1),
  });
  return last;
}

/** 실패 시 동기 롤백. 같은 id가 이미 있으면 아무것도 하지 않는다(재조회가 먼저
 * 되살린 경우 두 벌이 된다). 스트림 도중 statChange·endingReached는 messages를 만지지 않으므로
 * (applyStreamEvent.ts:29-49) 끝에 붙이는 것으로 충분하다. */
export function restoreMessage(queryClient: QueryClient, roomId: string, message: ChatMessage): void {
  queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) => {
    if (!prev) return prev;
    if (prev.messages.some((m) => m.id === message.id)) return prev;
    return { ...prev, messages: [...prev.messages, message] };
  });
}
