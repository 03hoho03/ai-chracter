import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverLedgerItem = components["schemas"]["CloverLedgerItem"];
export type CloverLedgerListResponse = components["schemas"]["CloverLedgerListResponse"];
export type CloverLedgerCategory = CloverLedgerItem["category"];

/** 내역 목록. "더 보기" 버튼형(`useProfileContentListQuery`
 * 선례 복제) — 내역은 탐색이 아니라 확인 대상이라 sentinel 무한스크롤이 아니라
 * 명시적 버튼이다. `category`는 BE가 `kind`→범주 맵으로 이미 분류해 응답에 실어 보낸다
 * (`CloverLedgerItem.category`) — FE는 같은 맵을 다시 두지 않고 탭 값을 그대로 쿼리 파라미터로
 * 넘긴다. */
export function useCloverLedgerQuery(category: CloverLedgerCategory) {
  // 타입인자를 하나라도 명시하면 나머지는 추론되지 않고 기본값으로 채워진다(TPageParam을 빼면
  // `unknown`으로 굳는다) — `useProfileContentListQuery`와 같은 이유.
  return useInfiniteQuery<
    CloverLedgerListResponse,
    ApiError,
    InfiniteData<CloverLedgerListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: cloverKeys.ledger(category),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<CloverLedgerListResponse>("/me/clover/ledger", {
          params: { category, cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
