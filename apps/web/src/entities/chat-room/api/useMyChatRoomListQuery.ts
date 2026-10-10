import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";

export type MyChatRoomListItem = components["schemas"]["MyChatRoomListItem"];

// "내 채팅목록"(`/chats`, 좌측 패널의 "최근 대화 전체 보기"·레일 아이콘, 좁은 화면은 드로어에서 간다)용 — 콘텐츠 스코프 없이 내 모든 대화방을 한 번에 받는다(GET /me/chat-rooms).
// gcTime은 기본값(5분) 유지: 썸네일 presigned URL은 받은 뒤 최소 15분 유효해 gcTime보다 길므로 재페인트되는 URL은 항상 만료 전이다.
// `viewerId` 가 없으면(세션을 잃은 뒤) 조회하지 않는다 — 키에 다른 사람의 목록을 받아 두지 않기 위해서다.
export function useMyChatRoomListQuery(viewerId: string | undefined) {
  return useQuery<MyChatRoomListItem[], ApiError>({
    queryKey: chatRoomKeys.myList(viewerId ?? ""),
    queryFn: async () => (await apiClient.get<MyChatRoomListItem[]>("/me/chat-rooms")).data,
    enabled: viewerId !== undefined,
  });
}
