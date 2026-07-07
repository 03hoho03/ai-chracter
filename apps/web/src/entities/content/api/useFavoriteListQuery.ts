import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { favoriteKeys } from "./keys";
import type { ContentListResponse } from "./useContentListQuery";

/** techspec-home-discovery.md §4 — 즐겨찾기 목록 무한스크롤. 캐릭터/스토리가 섞여 있어 §1의
 * `useContentListQuery`와 달리 `type`/정렬/필터 파라미터가 없다(GET /me/favorites, cursor만 사용). */
export function useFavoriteListQuery() {
  return useInfiniteQuery<ContentListResponse, ApiError>({
    queryKey: favoriteKeys.list(),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<ContentListResponse>("/me/favorites", {
          params: { cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
