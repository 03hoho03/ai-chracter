import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";
import type { MyChatRoomListItem } from "./useMyChatRoomListQuery";
import { RECENT_CHAT_ROOM_LIMIT, takeRecentChatRooms } from "../model/recentChatRooms";

/** 최근 활동순 내 대화방 앞 `RECENT_CHAT_ROOM_LIMIT` 개를 받는다. `limit` 을 무시하는 서버가 더 많이 줘도 앞에서 자른다. */
export async function fetchRecentChatRooms(): Promise<MyChatRoomListItem[]> {
  return takeRecentChatRooms(
    (await apiClient.get<MyChatRoomListItem[]>("/me/chat-rooms", { params: { limit: RECENT_CHAT_ROOM_LIMIT } })).data,
  );
}

/** 최근 활동순 내 대화방 앞 몇 개(GET /me/chat-rooms?limit=). 비로그인이면 401 이라 `viewerId` 가 있을 때만 조회한다.
 * 캐시 수명·재시도는 `/chats` 전체 목록과 같은 기본값이다. 이 앱에서 방이 바뀌는 곳(전송·생성·삭제·이름 변경·초기화
 * 등)은 `chatRoomKeys.myLists()` 를 무효화해 두 목록을 함께 갱신하고, 다른 탭에서 바뀐 것은 창 포커스 리페치가 메운다. */
export function useRecentChatRoomListQuery(viewerId: string | undefined) {
  return useQuery<MyChatRoomListItem[], ApiError>({
    queryKey: chatRoomKeys.myRecentList(viewerId ?? "", RECENT_CHAT_ROOM_LIMIT),
    queryFn: fetchRecentChatRooms,
    enabled: viewerId !== undefined,
  });
}
