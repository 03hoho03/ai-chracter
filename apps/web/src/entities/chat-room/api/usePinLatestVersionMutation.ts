import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatRoomState } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";
import { chatRoomMessageLimit } from "../model/messagePaging";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

/** 방을 최신 버전에 고정한다. 응답이 캐시를 통째로 바꾸므로 캐시가 들고 있는 깊이만큼 받아 위로 불러 둔 메시지가 잘리지
 * 않게 한다. */
export async function postPinLatestVersion(queryClient: QueryClient, roomId: string): Promise<ChatRoomState> {
  const messageLimit = chatRoomMessageLimit(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(roomId)));
  return toChatRoomState(
    (
      await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/pin-latest-version`, undefined, {
        params: { messageLimit },
      })
    ).data,
  );
}

// 응답이 이미 새 버전이 반영된 ChatRoomResponse 전체이므로,
// useResetChatRoomMutation과 동일하게 invalidate 대신 setQueryData로 캐시를 통째로 교체한다.
export function usePinLatestVersionMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, void>({
    mutationFn: () => postPinLatestVersion(queryClient, roomId),
    onSuccess: (room) => {
      queryClient.setQueryData(chatRoomKeys.detail(roomId), room);
      // 내 방 목록의 작품명·썸네일은 방이 고정한 버전 기준이라 함께 바뀐다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
    },
  });
}
