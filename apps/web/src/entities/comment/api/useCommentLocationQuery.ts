import { useQuery } from "@tanstack/react-query";

import { commentApi } from "./commentApi";
import { commentKeys } from "./keys";
import { retryCommentRead } from "./retryCommentRead";

export function useCommentLocationQuery(contentId: string, viewerId: string, commentId?: string) {
  return useQuery({
    queryKey: commentKeys.location(viewerId, contentId, commentId),
    queryFn: ({ signal }) => commentApi.location(contentId, commentId ?? "", signal),
    enabled: !!commentId,
    gcTime: 0,
    retry: retryCommentRead,
  });
}
