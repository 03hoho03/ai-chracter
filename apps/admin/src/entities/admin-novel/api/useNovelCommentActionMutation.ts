import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

export type AdminNovelCommentActionRequest = components["schemas"]["AdminNovelCommentActionRequest"];
export type NovelCommentAction = AdminNovelCommentActionRequest["action"];

/** 댓글 하나를 숨기거나(독자 목록에서 빠지고 본문은 남는다) 되돌리거나 지운다(본문을 비우고 되돌릴 수 없다). 지운 댓글은 409 — 끝나면
 * (409 포함) 노벨 쿼리를 무효화해 지금 상태를 다시 보인다. */
export function useNovelCommentActionMutation(commentId: string) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, AdminNovelCommentActionRequest>({
    mutationFn: async (payload) => {
      await apiClient.post(`/admin/novel-comments/${commentId}/actions`, payload);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
