import type { ApiError, components } from "@ai-character-chat/api-types";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { draftKeys } from "./keys";

export type DraftSummary = components["schemas"]["DraftSummary"];
export type DraftListResponse = components["schemas"]["DraftListResponse"];

/** techspec-builder-common.md §2 — 내 작품(`/my`)의 초안 목록.
 *
 * US-001로 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐고, US-009가 그 커서를 따라가는
 * "더 보기"를 붙였다. 이 목록에는 필터 축이 없어 쿼리키가 하나뿐이다 — 초안을 지우거나 새로 만드는
 * 뮤테이션이 `draftKeys.list()`를 invalidate하면 **불러 둔 페이지 전부**가 다시 조회된다(TanStack이
 * 무한쿼리를 그렇게 갱신한다). */
export function useDraftListQuery() {
  return useInfiniteQuery<DraftListResponse, ApiError>({
    queryKey: draftKeys.list(),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<DraftListResponse>("/me/drafts", { params: { cursor: pageParam } })).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
