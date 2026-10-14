import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { draftKeys } from "./keys";

export type DraftSummary = components["schemas"]["DraftSummary"];
export type DraftListResponse = components["schemas"]["DraftListResponse"];

/** 내 작품(`/my`)의 초안 목록.
 *
 * 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐고, 그 커서를 따라가는
 * "더 보기"가 붙었다. 필터 축은 제목 검색어(`q`) 하나라 쿼리키가 검색어마다 하나다 — 초안을 지우거나 새로
 * 만드는 뮤테이션이 접두사 `draftKeys.list()`를 invalidate하면 검색어와 무관하게 **불러 둔 페이지 전부**가 다시
 * 조회된다(TanStack이 무한쿼리를 그렇게 갱신한다).
 *
 * 키에서 바뀔 수 있는 칸이 검색어뿐이라 이전 목록을 늘 자리표시로 남긴다 — 이유는
 * `useProfileContentListQuery`와 같다(검색어를 칠 때마다 스켈레톤이 검색 칸을 언마운트시키지 않게). */
export function useDraftListQuery({ q }: { q?: string } = {}) {
  // 타입인자 명시 규칙은 useProfileContentListQuery와 같다 — TPageParam까지 줘야 pageParam이 unknown이 아니다.
  return useInfiniteQuery<
    DraftListResponse,
    ApiError,
    InfiniteData<DraftListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: draftKeys.listByQuery(q),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<DraftListResponse>("/me/drafts", { params: { q, cursor: pageParam } })).data,
    placeholderData: keepPreviousData,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
