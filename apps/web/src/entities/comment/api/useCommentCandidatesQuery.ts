import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import type { CommentMentionCandidates } from "../model/comment";
import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

export function useCommentCandidatesQuery(contentId: string, viewerId: string, q: string, enabled: boolean) {
  return useInfiniteQuery<CommentMentionCandidates, ApiError, InfiniteData<CommentMentionCandidates, string | undefined>, QueryKey, string | undefined>({
    queryKey: commentKeys.candidates(viewerId, contentId, q),
    queryFn: ({ pageParam, signal }) => commentApi.candidates(contentId, q, pageParam, signal),
    initialPageParam: undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    enabled,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
