import type { Comment } from "@/entities/comment";

import { EMPTY_COMMENT_VALUES, type CommentFormValues } from "./schema";
import { commentServerToForm } from "./serverToForm";

export type CommentDraft = { values: CommentFormValues; requestId: string };

export function newCommentDraft(comment?: Comment): CommentDraft {
  return {
    requestId: crypto.randomUUID(),
    values: comment ? commentServerToForm(comment) : { ...EMPTY_COMMENT_VALUES, mentions: [] },
  };
}

export function changeCommentDraft(draft: CommentDraft, values: CommentFormValues): CommentDraft {
  if (JSON.stringify(draft.values) === JSON.stringify(values)) return draft;
  // An edited payload is a deliberate new request; unchanged network retries retain their token.
  return { values, requestId: crypto.randomUUID() };
}

export function finishCommentDraft(draft: CommentDraft, sentRequestId: string): CommentDraft {
  return draft.requestId === sentRequestId ? newCommentDraft() : draft;
}
