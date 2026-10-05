import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toChatMessage } from "./toChatRoomState";
import { chatRoomKeys } from "./keys";
import type { ChatRoomState } from "../model/chatRoomState";
import { CHAT_ROOM_MESSAGE_PAGE_SIZE, prependOlderMessages, type OlderMessagesPage } from "../model/messagePaging";

type ChatMessagePageDto = components["schemas"]["ChatMessagePageResponse"];

// 위로 불러오기 — 지금 캐시의 첫 메시지 앞을 한 페이지 받아 같은 방 캐시 앞에 붙인다. 받기만 하는 요청이지만 결과를
// 캐시에 쓰는 일이 사용자 동작 한 번에 묶여 있어 뮤테이션으로 둔다(방 상세와 다른 캐시를 만들지 않는다).
export function useLoadOlderMessagesMutation(roomId: string) {
  const queryClient = useQueryClient();
  return useMutation<OlderMessagesPage, ApiError, string>({
    mutationFn: async (cursorId) => {
      const page = (
        await apiClient.get<ChatMessagePageDto>(`/chat-rooms/${roomId}/messages`, {
          params: { before: cursorId, limit: CHAT_ROOM_MESSAGE_PAGE_SIZE },
        })
      ).data;
      return { messages: page.messages.map(toChatMessage), hasMoreBefore: page.hasMoreBefore };
    },
    onSuccess: (page, cursorId) => {
      queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(roomId), (prev) =>
        prependOlderMessages(prev, page, cursorId),
      );
    },
  });
}
