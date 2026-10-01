import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import type { CommentList, CommentSort } from "../model/comment";
import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

// Responses contain current profile URLs and viewer-specific redaction; never share between accounts.
export function useCommentsQuery(contentId: string, viewerId: string, sort: CommentSort) {
  return useInfiniteQuery<CommentList, ApiError, InfiniteData<CommentList, string | undefined>, QueryKey, string | undefined>({
    queryKey: commentKeys.roots(viewerId, contentId, sort),
    queryFn: ({ pageParam, signal }) => commentApi.roots(contentId, sort, pageParam, signal),
    initialPageParam: undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
