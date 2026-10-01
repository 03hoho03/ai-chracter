import type { ApiError } from "@ai-character-chat/api-types";
import { useInfiniteQuery, type InfiniteData, type QueryKey } from "@tanstack/react-query";

import type { CommentReplies, ReplyPageParam } from "../model/comment";
import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

export function useCommentRepliesQuery(
  contentId: string, viewerId: string, rootId: string, enabled: boolean,
  anchor?: string, initial?: CommentReplies,
) {
  return useInfiniteQuery<CommentReplies, ApiError, InfiniteData<CommentReplies, ReplyPageParam>, QueryKey, ReplyPageParam>({
    queryKey: commentKeys.replies(viewerId, contentId, rootId, anchor),
    queryFn: async ({ pageParam, signal }) => {
      if (pageParam === undefined && anchor) {
        const located = await commentApi.location(contentId, anchor, signal);
        return located.replies ?? commentApi.replies(contentId, rootId, undefined, signal);
      }
      return commentApi.replies(contentId, rootId, pageParam, signal);
    },
    initialPageParam: undefined,
    getNextPageParam: (page): ReplyPageParam | undefined =>
      page.nextCursor ? { cursor: page.nextCursor, direction: "after" } : undefined,
    getPreviousPageParam: (page): ReplyPageParam | undefined =>
      page.previousCursor ? { cursor: page.previousCursor, direction: "before" } : undefined,
    initialData: initial ? { pages: [initial], pageParams: [undefined] } : undefined,
    enabled,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
