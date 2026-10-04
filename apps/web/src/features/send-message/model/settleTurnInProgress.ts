import type { QueryClient } from "@tanstack/react-query";

import { isChatTurnInProgressError, restoreMessages } from "@/entities/chat-room";
import type { ChatMessage } from "@/entities/chat-room";

/** 앞 턴이 아직 돌고 있어 서버가 이번 요청을 시작 전에 거절했는지 판정하고, 맞으면 캐시를 서버 쪽 사실에 맞춘다.
 * 서버는 아무것도 바꾸지 않았으므로 수정이 낙관적으로 잘라 둔 목록(`messagesBeforeEdit`)을 되돌린다. 보내기의 낙관적
 * 사용자 메시지는 남긴다 — 다시 보내기가 같은 요청을 다시 열기 때문이다(다른 오류와 같은 전제). */
export function settleTurnInProgress(
  queryClient: QueryClient,
  roomId: string,
  error: unknown,
  messagesBeforeEdit: ChatMessage[] | undefined,
): boolean {
  if (!isChatTurnInProgressError(error)) return false;
  if (messagesBeforeEdit) restoreMessages(queryClient, roomId, messagesBeforeEdit);
  return true;
}
