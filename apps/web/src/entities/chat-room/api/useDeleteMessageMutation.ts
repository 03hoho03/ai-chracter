import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toDeletedMessageStatRewind } from "./deleteMessageResponse";
import { chatRoomKeys } from "./keys";
import type { StatRewind } from "./chatStream";
import type { ChatRoomState } from "../model/chatRoomState";
import { removeDeletedMessage } from "../model/removeDeletedMessage";

// 서버는 갱신된 방을 돌려주지 않는다. 지운 메시지는 캐시에서 바로 빼고(`removeDeletedMessage`), 마지막 답을 지워 서버가
// 되돌린 스탯·턴 수는 방을 다시 받아 맞춘다. 결과로 서버가 스탯을 어떻게 했는지(`statRewind`)를 돌려준다 — 본문 없는 204 를
// 주는 옛 서버면 undefined 다.
export function useDeleteMessageMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<StatRewind | undefined, ApiError, string>({
    mutationFn: async (messageId) => {
      const response = await apiClient.delete<unknown>(`/chat-rooms/${roomId}/messages/${messageId}`);
      return toDeletedMessageStatRewind(response.data);
    },
    onSuccess: (_data, messageId) => {
      queryClient.setQueryData<ChatRoomState>(
        chatRoomKeys.detail(roomId),
        (prev) => prev && removeDeletedMessage(prev, messageId),
      );
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
      // 요약이 덮는 메시지를 지우면 서버가 요약을 이전 판으로 되돌린다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
      // 마지막 메시지를 지웠으면 내 방 목록의 미리보기·시각이 바뀐다.
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.myLists() });
    },
  });
}
