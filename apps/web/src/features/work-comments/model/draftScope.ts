import { finishCommentDraft, type CommentDraft } from "./drafts";

export type CommentDraftScope = {
  ownerId?: string;
  logoutRevision: number;
  drafts: Record<string, CommentDraft>;
  activeReplyId?: string;
  activeEditId?: string;
  generation: string;
};

export function resolveCommentDraftScope(
  current: CommentDraftScope | undefined, viewerId: string | undefined, logoutRevision: number,
  createDraft: () => CommentDraft,
): CommentDraftScope {
  if (!current || current.logoutRevision !== logoutRevision ||
    (viewerId && current.ownerId && viewerId !== current.ownerId)) {
    const root = createDraft();
    return { ownerId: viewerId, logoutRevision, generation: root.requestId, drafts: { root } };
  }
  // Guest -> first login claims the draft; a temporary 401 keeps its authenticated owner.
  if (viewerId && !current.ownerId) return { ...current, ownerId: viewerId };
  return current;
}

export function canUpdateCommentDraftScope(
  latest: CommentDraftScope | undefined, expected: CommentDraftScope,
  base: CommentDraftScope | undefined, latestLogoutRevision: number,
) {
  return expected.logoutRevision === latestLogoutRevision &&
    (latest?.generation === expected.generation || latest === base);
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
