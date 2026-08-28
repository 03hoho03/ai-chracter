import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { toChatRoomState } from "../model/toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "./chat-room";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

// US-079, techspec-content-versioning.md §3 — 응답이 이미 새 버전이 반영된 ChatRoomResponse 전체이므로,
// useResetChatRoomMutation(US-056)과 동일하게 invalidate 대신 setQueryData로 캐시를 통째로 교체한다.
export function usePinLatestVersionMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<ChatRoomState, ApiError, void>({
    mutationFn: async () =>
      toChatRoomState(
        (await apiClient.post<ChatRoomResponseDto>(`/chat-rooms/${roomId}/pin-latest-version`)).data,
      ),
    onSuccess: (room) => {
      queryClient.setQueryData(chatRoomKeys.detail(roomId), room);
    },
  });
}
