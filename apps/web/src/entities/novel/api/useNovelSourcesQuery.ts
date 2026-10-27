import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { novelKeys } from "./keys";

export type NovelSourceRoom = components["schemas"]["NovelSourceRoom"];
export type NovelSourceListResponse = components["schemas"]["NovelSourceListResponse"];

/** `GET /me/novel-sources` — 내 채팅방을 내 채팅 목록과 같은 순서로, 방마다 그 방의 소설 id 와 새 소설 만들기 막힘 여부를
 * 붙여 한 페이지씩. 고르는 목록이라 "더 보기" 버튼으로 당긴다. 소설화가 닫힌 계정은 403 `NOVELIZE_NOT_ALLOWED` 이고, 그
 * 응답이면 전역 처리가 세션을 다시 읽는다. */
export function useNovelSourcesQuery() {
  // 타입인자를 하나라도 적으면 나머지가 추론되지 않아 `TPageParam` 까지 함께 적는다.
  return useInfiniteQuery<NovelSourceListResponse, ApiError, InfiniteData<NovelSourceListResponse, string | undefined>, QueryKey, string | undefined>({
    queryKey: novelKeys.sources(),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<NovelSourceListResponse>("/me/novel-sources", { params: { cursor: pageParam } })).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
