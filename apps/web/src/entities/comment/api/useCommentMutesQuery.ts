import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import type { CommentMutes } from "../model/comment";
import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

export function useCommentMutesQuery(viewerId: string, enabled: boolean) {
  return useInfiniteQuery<CommentMutes, ApiError, InfiniteData<CommentMutes, string | undefined>, QueryKey, string | undefined>({
    queryKey: commentKeys.mutes(viewerId),
    queryFn: ({ pageParam, signal }) => commentApi.mutes(pageParam, signal),
    initialPageParam: undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    enabled,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
