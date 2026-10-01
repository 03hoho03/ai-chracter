import type { CommentDraft } from "./drafts";

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
