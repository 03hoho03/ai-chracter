import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { chatRoomKeys } from "./keys";

export type ChatRoomListItem = components["schemas"]["ChatRoomListItem"];

// techspec-chat-common.md §3 — 같은 콘텐츠(캐릭터/스토리)에 대한 내 대화방 목록. BE는 contentId로만
// 필터링하므로(GET /chat-rooms?contentId=) contentType은 쿼리 키 스코프용으로만 쓰인다.
export function useChatRoomListQuery({
  contentId,
  contentType,
}: {
  contentId: string;
  contentType: "character" | "story";
}) {
  return useQuery<ChatRoomListItem[], ApiError>({
    queryKey: chatRoomKeys.list({ contentId, contentType }),
    queryFn: async () =>
      (await apiClient.get<ChatRoomListItem[]>("/chat-rooms", { params: { contentId } })).data,
  });
}
