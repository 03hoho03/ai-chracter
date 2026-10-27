import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type DerivedWebnovelListResponse = components["schemas"]["DerivedNovelListResponse"];

/** `GET /contents/{id}/derived-novels` — 이 작품을 원작으로 한, 지금 읽을 수 있는 노벨(원작자 공식과 파생을 함께) 한 번에
 * 20편. 로그인 회원만 받는 API 라 호출부가 로그인했고 노벨이 열려 있을 때만 켠다(`enabled`). 노벨이 닫혔거나 원작자가
 * 숨겼으면 서버가 빈 목록을 준다. */
export function useDerivedWebnovelsQuery(contentId: string, { enabled }: { enabled: boolean }) {
  // 타입인자를 하나라도 적으면 나머지가 추론되지 않아 `TPageParam` 까지 함께 적는다.
  return useInfiniteQuery<
    DerivedWebnovelListResponse,
    ApiError,
    InfiniteData<DerivedWebnovelListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: webnovelKeys.derived(contentId),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<DerivedWebnovelListResponse>(`/contents/${contentId}/derived-novels`, {
          params: { cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled,
  });
}
