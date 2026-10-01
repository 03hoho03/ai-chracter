import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

export type MyChatRoomListItem = components["schemas"]["MyChatRoomListItem"];

// 헤더 "내 채팅목록"용 — 콘텐츠 스코프 없이 내 모든 대화방을 한 번에 받는다(GET /me/chat-rooms).
// gcTime은 기본값(5분) 유지: 썸네일 presigned URL은 받은 뒤 최소 15분 유효해 gcTime보다 길므로 재페인트되는 URL은 항상 만료 전이다.
export function useMyChatRoomListQuery() {
  return useQuery<MyChatRoomListItem[], ApiError>({
    queryKey: chatRoomKeys.myList(),
    queryFn: async () => (await apiClient.get<MyChatRoomListItem[]>("/me/chat-rooms")).data,
  });
}
