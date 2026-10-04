import type { QueryClient } from "@tanstack/react-query";

import { truncateAndEdit } from "@/entities/chat-room";
import type { ChatMessage, ChatStreamRequest } from "@/entities/chat-room";

/** 수정 요청이면 시도마다 캐시를 다시 잘라 두고, 되돌릴 목록은 **첫 시도의 것**을 돌려준다(수정이 아니면 그대로 넘긴다).
 * 호출부는 돌려받은 값을 재시도 요청에 실어 다음 시도에 `firstAttemptMessages` 로 넘긴다. 시도마다 그 시점 캐시에서
 * 다시 뜨면, 앞 시도가 다른 오류로 끝나 잘린 채 남은 목록을 "수정 전"으로 삼아 앞 턴 거절 때 잘린 목록을 되돌린다. */
export function truncateForEditAttempt(
  queryClient: QueryClient,
  roomId: string,
  payload: ChatStreamRequest,
  firstAttemptMessages: ChatMessage[] | undefined,
): ChatMessage[] | undefined {
  if (payload.kind !== "edit") return firstAttemptMessages;
  const beforeThisAttempt = truncateAndEdit(queryClient, roomId, payload.messageId, payload.content);
  return firstAttemptMessages ?? beforeThisAttempt;
}
