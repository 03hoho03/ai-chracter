import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelListItem = components["schemas"]["NovelListItem"];
export type NovelListResponse = components["schemas"]["NovelListResponse"];

/** `GET /novels` — 내 소설 목록. 최근 고친 순 커서 페이징이고, 원래 대화방이 지워진 소설(`chatRoomId` null)도
 * 함께 온다. 자기 것을 확인하는 목록이라 sentinel 무한스크롤이 아니라 "더 보기" 버튼으로 당긴다(클로버 내역과
 * 같은 이유). */
export function useNovelListQuery() {
  // 타입인자를 하나라도 적으면 나머지가 추론되지 않아 `TPageParam` 까지 함께 적는다.
  return useInfiniteQuery<NovelListResponse, ApiError, InfiniteData<NovelListResponse, string | undefined>, QueryKey, string | undefined>({
    queryKey: novelKeys.list(),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<NovelListResponse>("/novels", { params: { cursor: pageParam } })).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
