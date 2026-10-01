import type { components } from "@ai-character-chat/api-types";

import type { Comment, CommentCreateRequest, CommentWriteRequest } from "@/entities/comment";

import type { NotificationPreferenceFormValues } from "./notificationPreferenceSchema";
import type { CommentFormValues } from "./schema";

export function commentFormToServer(values: CommentFormValues): CommentWriteRequest {
  return {
    body: values.body, stickerId: values.stickerId, isSpoiler: values.isSpoiler,
    mentionUserIds: values.mentions.map((author) => author.id),
  };
}

/** 답글이면 대상이 원댓글이든 답글이든 스레드의 원댓글 id와 직접 답한 댓글 id를 함께 보낸다. */
export function commentCreateToServer(values: CommentFormValues, requestId: string, replyTarget?: Comment): CommentCreateRequest {
  return {
    ...commentFormToServer(values), requestId,
    rootCommentId: replyTarget ? replyTarget.rootCommentId ?? replyTarget.id : null,
    replyToCommentId: replyTarget?.id ?? null,
  };
}

export function notificationPreferenceFormToServer(values: NotificationPreferenceFormValues): components["schemas"]["CommentNotificationPreferencesUpdateRequest"] {
  return { newComment: values.isNewCommentEnabled, reply: values.isReplyEnabled, mention: values.isMentionEnabled };
}
