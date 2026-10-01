import { useMutation, useQueryClient } from "@tanstack/react-query";

import { commentApi, commentKeys, type Comment } from "@/entities/comment";
import { notificationKeys, redactNotificationCaches } from "@/entities/notification";

import { commentCreateToServer, commentFormToServer } from "../model/formToServer";
import type { CommentFormValues } from "../model/schema";

type WriteCommentOptions = {
  contentId: string; viewerId: string; editCommentId?: string; replyTarget?: Comment; requestId: string;
};

export function useWriteCommentMutation({ contentId, viewerId, editCommentId, replyTarget, requestId }: WriteCommentOptions) {
  const client = useQueryClient();
  return useMutation({
    // 계정이 바뀐 뒤 재접속하면 옛 초안이 자동 전송되는 대신 즉시 실패한다.
    networkMode: "always",
    mutationFn: (values: CommentFormValues) => editCommentId
      ? commentApi.update(editCommentId, commentFormToServer(values))
      : commentApi.create(contentId, commentCreateToServer(values, requestId,
        replyTarget ? replyTarget.rootCommentId ?? replyTarget.id : null, replyTarget?.id ?? null)),
    onSuccess: async (comment) => {
      if (editCommentId) await redactNotificationCaches(client, viewerId, { commentId: comment.id });
      await Promise.all([
        client.invalidateQueries({ queryKey: commentKeys.content(viewerId, contentId) }),
        client.invalidateQueries({ queryKey: notificationKeys.viewer(viewerId) }),
      ]);
    },
    onError: () => { void client.invalidateQueries({ queryKey: commentKeys.content(viewerId, contentId) }); },
  });
}
