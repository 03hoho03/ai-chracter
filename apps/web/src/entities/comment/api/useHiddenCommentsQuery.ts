import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import type { CommentHiddenList } from "../model/comment";
import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

export function useHiddenCommentsQuery(contentId: string, viewerId: string, enabled: boolean) {
  return useInfiniteQuery<CommentHiddenList, ApiError, InfiniteData<CommentHiddenList, string | undefined>, QueryKey, string | undefined>({
    queryKey: commentKeys.hidden(viewerId, contentId),
    queryFn: ({ pageParam, signal }) => commentApi.hidden(contentId, pageParam, signal),
    initialPageParam: undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    enabled,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
