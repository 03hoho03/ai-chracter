import type { ApiError, components } from "@ai-character-chat/api-types";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { contentKeys, type ContentBrowseParams } from "./keys";

export type ContentListItem = components["schemas"]["ContentListItem"];
export type ContentListResponse = components["schemas"]["ContentListResponse"];

/** techspec-home-discovery.md §1 — 홈 무한스크롤 리스트. `type`은 헤더 전역 토글, 나머지(sort/genre/
 * creator/hashtag/q)는 홈 라우트 search param에서 온다. 정렬/필터가 바뀌면 쿼리키가 바뀌어 첫 페이지부터
 * 다시 로딩된다(US-007 AC의 "로딩 표시"는 별도 상태 없이 이 쿼리의 `isPending`을 그대로 쓴다). */
export function useContentListQuery(params: ContentBrowseParams) {
  return useInfiniteQuery<ContentListResponse, ApiError>({
    queryKey: contentKeys.browse(params),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<ContentListResponse>("/contents", {
          params: { ...params, cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
