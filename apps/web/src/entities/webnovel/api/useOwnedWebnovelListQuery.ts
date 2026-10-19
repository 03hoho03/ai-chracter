import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type OwnedWebnovelItem = components["schemas"]["PublicNovelOwnedItem"];
export type OwnedWebnovelListResponse = components["schemas"]["PublicNovelOwnedListResponse"];

/** `GET /webnovels/owned` — 내가 소장한 노벨(아직 돌려받지 않은 화가 하나라도 있고 지금 작품 정보가 열리는 것), 20편씩.
 * 노벨 목록의 최신순과 같은 순서(공개 글이 마지막으로 바뀐 시각)라 산 순서가 아니다. 판매를 멈춘 노벨은
 * `salesStopped` 가 참이다 — 노벨 목록에서는 빠져 소장자가 다시 찾아 들어오는 길이 여기뿐이다. 같은 작품이 페이지
 * 경계에서 두 번 올 수 있는 것은 노벨 목록과 같아 화면이 id 로 한 번 거른다. */
export function useOwnedWebnovelListQuery(options: { enabled: boolean }) {
  return useInfiniteQuery<
    OwnedWebnovelListResponse,
    ApiError,
    InfiniteData<OwnedWebnovelListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: webnovelKeys.owned(),
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<OwnedWebnovelListResponse>("/webnovels/owned", { params: { cursor: pageParam } })).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: options.enabled,
  });
}
