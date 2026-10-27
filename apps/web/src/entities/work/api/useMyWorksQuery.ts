import type { ApiError } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { hashKey, useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { MyWorksParams, WorkListResponse } from "../model/workItem";
import { workKeys } from "./keys";

/** `GET /me/works` — 내 캐릭터·스토리(초안 포함)와 소설(소설화 허용 계정만)을 마지막 편집 순으로 한 목록에. 조건과
 * 커서를 페이지마다 함께 싣는다(서버 커서가 조건을 담지 않는다).
 *
 * **검색어만 바뀐 새 쿼리는 이전 목록을 자리표시로 남긴다** — 한 글자 칠 때마다 스켈레톤으로 빠지면 검색 칸까지
 * 언마운트돼 입력 중인 포커스가 날아간다. 유형·상태가 바뀐 경우는 남기지 않는다(다른 조건의 목록을 잠깐이라도 이 조건의
 * 결과처럼 보이면 안 된다). 내 작품 목록 훅들과 같은 규칙이다. */
export function useMyWorksQuery(params: MyWorksParams) {
  const queryKey = workKeys.list(params);

  // 타입인자를 하나라도 명시하면 나머지는 기본값으로 채워진다 — TPageParam까지 줘야 pageParam이 unknown이 아니다.
  return useInfiniteQuery<
    WorkListResponse,
    ApiError,
    InfiniteData<WorkListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey,
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<WorkListResponse>("/me/works", {
          params: { type: params.type, status: params.status, q: params.q, cursor: pageParam },
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
