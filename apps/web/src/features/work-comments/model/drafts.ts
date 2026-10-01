import type { Comment } from "@/entities/comment";

import type { CommentDraftScope } from "./draftScope";
import { EMPTY_COMMENT_VALUES, type CommentFormValues } from "./schema";

export type CommentDraft = { values: CommentFormValues; requestId: string };

export function newCommentDraft(comment?: Comment): CommentDraft {
  return {
    requestId: crypto.randomUUID(),
    values: comment ? {
      body: comment.body ?? "", stickerId: comment.sticker?.id ?? null,
      isSpoiler: comment.isSpoiler, mentions: comment.mentions,
    } : { ...EMPTY_COMMENT_VALUES, mentions: [] },
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

export function finishCommentDraftScope(scope: CommentDraftScope, key: string, requestId: string): CommentDraftScope {
  const draft = scope.drafts[key];
  if (!draft) return scope;
  const next = { ...scope, drafts: { ...scope.drafts, [key]: finishCommentDraft(draft, requestId) } };
  const isCleared = draft.requestId === requestId || (draft.values.body === "" && !draft.values.stickerId && draft.values.mentions.length === 0);
  if (isCleared && key === "reply:" + scope.activeReplyId) next.activeReplyId = undefined;
  if (isCleared && key === "edit:" + scope.activeEditId) next.activeEditId = undefined;
  return next;
}
