import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";
import { chatRoomMessageLimit } from "../model/messagePaging";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

/** 재생성이 밀어낸 직전 응답으로 되돌린다(`messageId` 는 지금 보이는 응답). 응답이 캐시를 통째로 바꾸므로 캐시가 들고 있는
 * 깊이만큼 받아 위로 불러 둔 메시지가 잘리지 않게 한다. */
export async function postRestorePreviousResponse(
  queryClient: QueryClient,
  roomId: string,
  messageId: string,
): Promise<ChatRoomState> {
  const messageLimit = chatRoomMessageLimit(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId)));
  return toChatRoomState(
    (
      await apiClient.post<ChatRoomResponseDto>(
        `/chat-rooms/${roomId}/messages/${messageId}/restore-previous`,
        undefined,
        { params: { messageLimit } },
      )
    ).data,
  );
}

/** 되돌린 방 상태로 캐시를 바꾼다. 옛 답과 새 답을 한 번에 맞바꾸므로 둘이 함께 보이는 렌더가 없고, 스탯도 서버가 되돌린 값이
 * 그대로 들어간다.
 * 바꾸기 전에 진행 중인 방 조회를 끊는다 — 되돌리기 전에 떠난 조회(탭 복귀 재조회 등)가 뒤늦게 도착하면 되돌린 답을 옛 답으로
 * 덮는다. 끊긴 조회는 시작 시점 캐시로 돌아가는데, 그 값은 곧바로 아래에서 덮인다. */
export async function applyRestoredRoom(queryClient: QueryClient, roomId: string, room: ChatRoomState): Promise<void> {
  await queryClient.cancelQueries({ queryKey: chatRoomKeys.detail(roomId) });
  queryClient.setQueryData(chatRoomKeys.detail(roomId), room);
  // 되돌린 응답 뒤를 덮던 요약은 서버가 되감는다 — 기억은 낡은 값이 되므로 다시 받게 표시한다.
  void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
  // 내 방 목록의 미리보기가 되살린 응답으로 바뀐다.
  void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
}

export function useRestorePreviousResponseMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, string>({
    mutationFn: (messageId) => postRestorePreviousResponse(queryClient, roomId, messageId),
    onSuccess: (room) => applyRestoredRoom(queryClient, roomId, room),
  });
}
