import { useEffect } from "react";
import { useAtom, useAtomValue, useStore } from "jotai";

import { commentDraftLogoutRevisionAtom, type Comment } from "@/entities/comment";

import { draftScopesAtom } from "./atoms";
import { canUpdateCommentDraftScope, resolveCommentDraftScope } from "./draftScope";
import { changeCommentDraft, finishCommentDraftScope, newCommentDraft, type CommentDraft } from "./drafts";
import type { CommentFormValues } from "./schema";

export function useCommentDrafts(contentId: string, viewerId: string | undefined) {
  const revision = useAtomValue(commentDraftLogoutRevisionAtom);
  const store = useStore();
  const [scopes, setScopes] = useAtom(draftScopesAtom);
  const current = scopes[contentId];
  const scope = resolveCommentDraftScope(current, viewerId, revision, newCommentDraft);
  const drafts = scope.drafts;
  useEffect(() => {
    if (scope !== current) setScopes((previous) => canUpdateCommentDraftScope(previous[contentId], scope, current,
      store.get(commentDraftLogoutRevisionAtom)) ? { ...previous, [contentId]: scope } : previous);
  }, [scope, current, setScopes, contentId, store]);
  function setDrafts(update: (current: Record<string, CommentDraft>) => Record<string, CommentDraft>) {
    setScopes((previous) => {
      if (!canUpdateCommentDraftScope(previous[contentId], scope, current, store.get(commentDraftLogoutRevisionAtom))) return previous;
      const active = resolveCommentDraftScope(previous[contentId], viewerId, revision, newCommentDraft);
      const retained = Object.fromEntries(Object.entries(previous).filter(([, value]) => value.logoutRevision === revision));
      return { ...retained, [contentId]: { ...active, drafts: update(active.drafts) } };
    });
  }
  function ensureDraft(key: string, comment?: Comment) {
    setDrafts((current) => current[key] ? current : { ...current, [key]: newCommentDraft(comment) });
  }
  function changeDraft(key: string, values: CommentFormValues) {
    setDrafts((current) => {
      const draft = current[key];
      if (!draft) return current;
      const next = changeCommentDraft(draft, values);
      return next === draft ? current : { ...current, [key]: next };
    });
  }
  function finishDraft(key: string, requestId: string) {
    setScopes((previous) => {
      if (!canUpdateCommentDraftScope(previous[contentId], scope, current, store.get(commentDraftLogoutRevisionAtom))) return previous;
      const active = resolveCommentDraftScope(previous[contentId], viewerId, revision, newCommentDraft);
      return { ...previous, [contentId]: finishCommentDraftScope(active, key, requestId) };
    });
  }
  function selectActiveDraft(name: "activeReplyId" | "activeEditId", commentId: string | undefined) {
    setScopes((previous) => {
      if (!canUpdateCommentDraftScope(previous[contentId], scope, current, store.get(commentDraftLogoutRevisionAtom))) return previous;
      const active = resolveCommentDraftScope(previous[contentId], viewerId, revision, newCommentDraft);
      return { ...previous, [contentId]: { ...active, [name]: commentId } };
    });
  }
  return { drafts, ensureDraft, changeDraft, finishDraft,
    selectReplyDraft: (id: string | undefined) => selectActiveDraft("activeReplyId", id),
    selectEditDraft: (id: string | undefined) => selectActiveDraft("activeEditId", id),
    activeReplyId: scope.activeReplyId, activeEditId: scope.activeEditId,
    scopeKey: revision + ":" + (scope.ownerId ?? "guest") };
}
