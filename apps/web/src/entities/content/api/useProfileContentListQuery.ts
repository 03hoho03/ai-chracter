import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { hashKey, useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { ContentType } from "../model/content";
import type { VisibilityFilter } from "../model/visibilityFilter";
import { contentKeys } from "./keys";

export type ContentSummary = components["schemas"]["ContentSummary"];
export type ContentSummaryListResponse = components["schemas"]["ContentSummaryListResponse"];

/** 프로필 작품 목록. 본인 조회일 때만 visibilityFilter를
 * 넘긴다(타인 조회는 서버가 무시하므로 굳이 생략할 필요는 없지만, 필터 UI 자체가 본인에게만 노출된다).
 *
 * 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐고, 그 커서를 따라가는
 * "더 보기"가 붙었다 — 홈·즐겨찾기와 같은 `useInfiniteQuery`다(다른 건 sentinel 대신 명시적 버튼인
 * 호출부뿐이다). 필터가 바뀌면 `contentKeys.list`가 바뀌어 **그 자체로 첫 페이지부터 새 쿼리**가 되므로
 * 이전 필터의 커서가 남지 않는다.
 *
 * `q`는 제목 검색어다(내 작품 화면만 넘긴다). 서버가 페이지마다 다시 걸어야 하므로 커서와 함께 매 요청에 싣는다.
 * **검색어만 바뀐 새 쿼리는 이전 목록을 자리표시로 남긴다** — 안 그러면 한 글자 칠 때마다 쿼리가 `isPending`으로
 * 돌아가 화면이 스켈레톤으로 빠지고, 그 스켈레톤이 검색 칸까지 언마운트시켜 입력 중인 포커스가 날아간다.
 * 유형·공개범위가 바뀐 경우는 남기지 않는다(다른 목록을 잠깐이라도 이 필터의 결과처럼 보이면 안 된다). */
export function useProfileContentListQuery({
  userId,
  type,
  visibilityFilter,
  q,
}: {
  userId: string;
  type: ContentType;
  visibilityFilter?: VisibilityFilter;
  q?: string;
}) {
  const queryKey = contentKeys.list(userId, type, visibilityFilter, q);

  // 타입인자를 하나라도 명시하면 나머지는 추론되지 않고 기본값으로 채워진다 — TPageParam을 빼면
  // `unknown`으로 굳어 `initialPageParam`의 타입이 queryFn의 `pageParam`에 전달되지 않는다.
  return useInfiniteQuery<
    ContentSummaryListResponse,
    ApiError,
    InfiniteData<ContentSummaryListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey,
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<ContentSummaryListResponse>(`/users/${userId}/contents`, {
          params: { type, visibility: visibilityFilter, q, cursor: pageParam },
        })
      ).data,
    placeholderData: (previous, previousQuery) =>
      previousQuery !== undefined && hashKey(previousQuery.queryKey.slice(0, -1)) === hashKey(queryKey.slice(0, -1))
        ? previous
        : undefined,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
