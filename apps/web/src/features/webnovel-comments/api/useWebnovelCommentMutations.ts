import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { webnovelKeys, type WebnovelComment } from "@/entities/webnovel";
import { apiClient } from "@/shared/api/client";

/** `POST /webnovels/{novelId}/chapters/{chapterId}/comments` — 화 댓글 쓰기. 그 화의 댓글 목록(첫 페이지의 수 포함)이
 * 낡으므로 다시 받는다. */
export function useCreateWebnovelCommentMutation(novelId: string, chapterId: string) {
  const queryClient = useQueryClient();
  return useMutation<WebnovelComment, ApiError, string>({
    mutationFn: async (body) =>
      (await apiClient.post<WebnovelComment>(`/webnovels/${novelId}/chapters/${chapterId}/comments`, { body })).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.comments(novelId, chapterId) });
    },
  });
}

/** `DELETE /webnovels/{novelId}/comments/{commentId}` — 내 댓글이나(게시자면) 내 노벨의 댓글을 지운다(204). 이미 지운
 * 댓글(404)도 목록을 다시 받으면 맞아진다. */
export function useDeleteWebnovelCommentMutation(novelId: string, chapterId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (commentId) => {
      await apiClient.delete(`/webnovels/${novelId}/comments/${commentId}`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: webnovelKeys.comments(novelId, chapterId) });
    },
  });
}
