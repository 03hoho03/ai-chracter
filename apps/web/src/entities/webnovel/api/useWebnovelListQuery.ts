import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys, type WebnovelListSort } from "./keys";

export type WebnovelListItem = components["schemas"]["PublicNovelListItem"];
export type WebnovelListResponse = components["schemas"]["PublicNovelListResponse"];
export type WebnovelSource = components["schemas"]["PublicNovelSource"];

/** `GET /webnovels` — 노벨 목록, 한 번에 20편. 다음 페이지는 `nextCursor` 로 당긴다(sentinel 무한 스크롤). 서버
 * 커서는 정렬 키가 같은 작품이 페이지 경계에 걸리면 같은 작품을 두 번 줄 수 있어 화면이 id 로 한 번 거른다
 * (`toUniqueWebnovels`). */
export function useWebnovelListQuery(sort: WebnovelListSort) {
  // 타입인자를 하나라도 적으면 나머지가 추론되지 않아 `TPageParam` 까지 함께 적는다.
  return useInfiniteQuery<WebnovelListResponse, ApiError, InfiniteData<WebnovelListResponse, string | undefined>, QueryKey, string | undefined>({
    queryKey: webnovelKeys.list(sort),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<WebnovelListResponse>("/webnovels", { params: { sort, cursor: pageParam } })).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
