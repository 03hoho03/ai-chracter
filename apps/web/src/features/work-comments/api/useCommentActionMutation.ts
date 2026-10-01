import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { commentApi, commentKeys, redactCommentCaches, type CommentReportReason } from "@/entities/comment";
import { notificationKeys, redactNotificationCaches } from "@/entities/notification";

import { commentErrorMessage } from "../model/commentError";

export type CommentAction =
  | { type: "delete"; commentId: string }
  | { type: "pin"; contentId: string; commentId?: string }
  | { type: "creator-hide"; commentId: string; isHidden: boolean; shouldHideThread?: boolean }
  | { type: "report"; commentId: string; reason: CommentReportReason }
  | { type: "mute"; authorId: string };

export function useCommentActionMutation(viewerId: string) {
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: async (action: CommentAction) => {
      switch (action.type) {
        case "delete":
          await commentApi.delete(action.commentId);
          await redactCommentCaches(client, viewerId, { commentId: action.commentId, state: "deleted" });
          await redactNotificationCaches(client, viewerId, { commentId: action.commentId });
          return;
        case "pin":
          await commentApi.pin(action.contentId, action.commentId ?? null);
          return;
        case "creator-hide":
          await commentApi.hide(action.commentId, action.isHidden);
          if (action.isHidden) {
            await redactCommentCaches(client, viewerId, { commentId: action.commentId, state: "creator-hidden" });
            await redactNotificationCaches(client, viewerId, { commentId: action.commentId, shouldHideThread: action.shouldHideThread });
          }
          return;
        case "report":
          await commentApi.report(action.commentId, action.reason);
          return;
        case "mute":
          await commentApi.mute(action.authorId, true);
          await redactCommentCaches(client, viewerId, { mutedUserId: action.authorId, state: "muted" });
          await redactNotificationCaches(client, viewerId, { mutedUserId: action.authorId });
      }
    },
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: commentKeys.viewer(viewerId) }),
      client.invalidateQueries({ queryKey: notificationKeys.viewer(viewerId) }),
    ]),
    onError: (error) => { toast.error(commentErrorMessage(error)); },
  });
}
