import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { toNextStatementsCursor } from "../model/statementsCursor";
import { creatorPayoutKeys } from "./keys";

export type CreatorPayoutStatement = components["schemas"]["CreatorPayoutStatementView"];
export type CreatorPayoutStatementLine = components["schemas"]["CreatorPayoutStatementLineView"];
type CreatorPayoutStatementsResponse = components["schemas"]["CreatorPayoutStatementsResponse"];

/** 확정된 정산 내역(최신순). 내역은 탐색이 아니라 확인 대상이라 sentinel 무한스크롤이 아니라 "더 보기" 버튼으로
 * 넘긴다(클로버 내역과 같다). */
export function useCreatorPayoutStatementsQuery() {
  // 타입인자를 하나라도 명시하면 나머지는 추론되지 않고 기본값으로 채워진다(TPageParam 을 빼면 `unknown` 으로 굳는다).
  return useInfiniteQuery<
    CreatorPayoutStatementsResponse,
    ApiError,
    InfiniteData<CreatorPayoutStatementsResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: creatorPayoutKeys.statements(),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<CreatorPayoutStatementsResponse>("/me/creator-payout/statements", {
          params: { cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined,
    getNextPageParam: toNextStatementsCursor,
  });
}
