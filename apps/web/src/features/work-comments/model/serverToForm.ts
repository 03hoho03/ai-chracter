import type { Comment, CommentPreferences } from "@/entities/comment";

import type { NotificationPreferenceFormValues } from "./notificationPreferenceSchema";
import type { CommentFormValues } from "./schema";

/** 수정할 댓글을 폼 값으로 펼친다. 본문이 없는 스티커 댓글은 빈 문자열로 받는다. */
export function commentServerToForm(comment: Comment): CommentFormValues {
  return {
    body: comment.body ?? "", stickerId: comment.sticker?.id ?? null,
    isSpoiler: comment.isSpoiler, mentions: comment.mentions,
  };
}

export function notificationPreferenceServerToForm(preferences: CommentPreferences): NotificationPreferenceFormValues {
  return {
    isNewCommentEnabled: preferences.newComment,
    isReplyEnabled: preferences.reply,
    isMentionEnabled: preferences.mention,
  };
}
