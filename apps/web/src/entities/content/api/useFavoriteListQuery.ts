import type { ApiError } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { ContentType } from "../model/content";
import { favoriteKeys } from "./keys";
import type { ContentListResponse } from "./useContentListQuery";

/** techspec-home-discovery.md §4 — 즐겨찾기 목록 무한스크롤. `type`은 D-6(card-grid-goal-prompt.md)로
 * 그리드가 항상 단일 타입이어야 해서 필수가 됐다(GET /me/favorites?type=, cursor와 함께 사용). 정렬·
 * 그 밖의 필터는 여전히 없다. */
export function useFavoriteListQuery(type: ContentType) {
  return useInfiniteQuery<
    ContentListResponse,
    ApiError,
    InfiniteData<ContentListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: favoriteKeys.list(type),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<ContentListResponse>("/me/favorites", {
          params: { type, cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
