import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { chatRoomKeys } from "./keys";
import { toChatRoomMemoryItemsPage } from "./toChatRoomMemoryItems";
import {
  mergeMemoryItemPages,
  type ChatRoomMemoryItems,
  type ChatRoomMemoryItemsPage,
} from "../model/chatRoomMemoryItems";

type ChatRoomMemoryItemsDto = components["schemas"]["ChatRoomMemoryItemsResponse"];

/** 방의 장면·사실 기억. 장면은 30개씩 "더 보기"로 이어 받고, 사실은 페이지마다 전부 온다.
 *
 * 스위치가 꺼져 있으면 라우트가 404라, 이 훅을 쓰는 화면은 기억 응답의 `features.itemsVisible`이 참일 때만 마운트한다(기억
 * 패널의 탭이 그렇다). 패널의 탭 개수와 두 목록 탭이 같은 캐시를 본다(`select`가 페이지를 한 목록으로 합친다). */
export function useChatRoomMemoryItemsQuery(roomId: string) {
  return useInfiniteQuery<
    ChatRoomMemoryItemsPage,
    ApiError,
    ChatRoomMemoryItems,
    QueryKey,
    string | undefined
  >({
    queryKey: chatRoomKeys.memoryItems(roomId),
    queryFn: async ({ pageParam }) =>
      toChatRoomMemoryItemsPage(
        (
          await apiClient.get<ChatRoomMemoryItemsDto>(`/chat-rooms/${roomId}/memory/items`, {
            params: { cursor: pageParam },
          })
        ).data,
      ),
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor,
    select: (data: InfiniteData<ChatRoomMemoryItemsPage, string | undefined>) => mergeMemoryItemPages(data.pages),
  });
}
