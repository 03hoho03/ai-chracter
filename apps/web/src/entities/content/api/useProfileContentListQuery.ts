import type { ApiError, components } from "@ai-character-chat/api-types";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import type { ContentType } from "../model/content";
import type { VisibilityFilter } from "../model/visibilityFilter";
import { contentKeys } from "./keys";

export type ContentSummary = components["schemas"]["ContentSummary"];
export type ContentSummaryListResponse = components["schemas"]["ContentSummaryListResponse"];

/** techspec-global-nav-profile.md §3.2 — 프로필 작품 목록. 본인 조회일 때만 visibilityFilter를
 * 넘긴다(타인 조회는 서버가 무시하므로 굳이 생략할 필요는 없지만, 필터 UI 자체가 본인에게만 노출된다).
 *
 * US-001로 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐고, US-009가 그 커서를 따라가는
 * "더 보기"를 붙였다 — 홈·즐겨찾기와 같은 `useInfiniteQuery`다(다른 건 sentinel 대신 명시적 버튼인
 * 호출부뿐이다). 필터가 바뀌면 `contentKeys.list`가 바뀌어 **그 자체로 첫 페이지부터 새 쿼리**가 되므로
 * 이전 필터의 커서가 남지 않는다. */
export function useProfileContentListQuery({
  userId,
  type,
  visibilityFilter,
}: {
  userId: string;
  type: ContentType;
  visibilityFilter?: VisibilityFilter;
}) {
  return useInfiniteQuery<ContentSummaryListResponse, ApiError>({
    queryKey: contentKeys.list(userId, type, visibilityFilter),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<ContentSummaryListResponse>(`/users/${userId}/contents`, {
          params: { type, visibility: visibilityFilter, cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
