import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

type ChatRoomResponseDto = components["schemas"]["ChatRoomResponse"];

/** 구간 고르기가 읽는 메시지 한 개 — 글과 말한 쪽, 그리고 순서 키의 시각(`createdAt`). 지워진 끝 메시지의 자리를 이 시각으로 잡는다. */
export type ChatRoomSourceMessage = { id: string; role: "user" | "assistant"; content: string; createdAt: string };

/** 방의 메시지 전부(`GET /chat-rooms/{id}` 를 `messageLimit` 없이 — 서버가 다 싣는다). 순서는 소설 구간 선택의 관문과 같은
 * `(created_at, id)` 오름차순이다. 글·말한 쪽·시각만 남긴다 — 함께 오는 그림의 서명 주소를 캐시에 들고 있지 않는다. */
export function useChatRoomSourceMessagesQuery(roomId: string | null, options: { enabled: boolean }) {
  return useQuery<ChatRoomSourceMessage[], ApiError>({
    queryKey: chatRoomKeys.sourceMessages(roomId ?? ""),
    queryFn: async () =>
      (await apiClient.get<ChatRoomResponseDto>(`/chat-rooms/${roomId}`)).data.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        createdAt: message.createdAt,
      })),
    enabled: options.enabled && roomId !== null,
  });
}
