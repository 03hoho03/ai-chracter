import type { CommentCreateRequest, CommentWriteRequest } from "@/entities/comment";

import type { CommentFormValues } from "./schema";

export function commentFormToServer(values: CommentFormValues): CommentWriteRequest {
  return {
    body: values.body, stickerId: values.stickerId, isSpoiler: values.isSpoiler,
    mentionUserIds: values.mentions.map((author) => author.id),
  };
}

export function commentCreateToServer(
  values: CommentFormValues, requestId: string, rootCommentId: string | null, replyToCommentId: string | null,
): CommentCreateRequest {
  return { ...commentFormToServer(values), requestId, rootCommentId, replyToCommentId };
}
