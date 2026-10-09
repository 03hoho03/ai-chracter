import type { ApiError, components } from "@ai-character-chat/api-types";
import type { InfiniteData, QueryKey } from "@tanstack/react-query";
import { useInfiniteQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type WebnovelComment = components["schemas"]["PublicNovelCommentItem"];
export type WebnovelCommentListResponse = components["schemas"]["PublicNovelCommentListResponse"];

/** `GET /webnovels/{novelId}/chapters/{chapterId}/comments` — 화 댓글 최신순 20개씩. 첫 페이지의 `totalCount` 가 그 화에
 * 보이는 댓글 수다(화 끝 "댓글 12" 버튼이 같은 쿼리를 읽는다). 볼 수 없는 화(소장하지 않은 유료 화)는 서버가 막으므로
 * 화면도 그런 화에서는 부르지 않는다. */
export function useWebnovelCommentsQuery(novelId: string, chapterId: string) {
  return useInfiniteQuery<
    WebnovelCommentListResponse,
    ApiError,
    InfiniteData<WebnovelCommentListResponse, string | undefined>,
    QueryKey,
    string | undefined
  >({
    queryKey: webnovelKeys.comments(novelId, chapterId),
    queryFn: async ({ pageParam }) =>
      (
        await apiClient.get<WebnovelCommentListResponse>(`/webnovels/${novelId}/chapters/${chapterId}/comments`, {
          params: { cursor: pageParam },
        })
      ).data,
    initialPageParam: undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
