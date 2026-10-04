import type { QueryClient } from "@tanstack/react-query";

import { chatRoomKeys, roomAuthorMacroNames, type ChatRoomState } from "@/entities/chat-room";
import { expandAuthorMacros } from "@/shared/lib/text/authorMacros";

/**
 * 사용자가 보내는 글 속 `{{user}}`·`{{char}}` 를 방의 이름으로 바꾼다 — 입력창·추천 답변·단축어 프롬프트·편집이 모두
 * 전송 훅에서 이 함수를 지나고, 바꾼 글이 낙관적 메시지와 서버에 함께 간다. 저장된 사용자 메시지는 그 뒤 프로필이
 * 바뀌어도 그대로다(서버는 사용자 메시지를 다시 바꾸지 않는다). 이름은 보내는 순간의 방 캐시에서 읽는다 — 화면이 칩과
 * 첫 메시지에 그린 이름과 같다. 방이 캐시에 없으면(보낼 화면이 없다) 글을 그대로 돌려준다.
 */
export function expandUserTextForRoom(queryClient: QueryClient, roomId: string, text: string): string {
  const room = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId));
  return room === undefined ? text : expandAuthorMacros(text, roomAuthorMacroNames(room));
}
