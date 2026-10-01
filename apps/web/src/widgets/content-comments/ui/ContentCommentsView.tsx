import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { toast } from "sonner";

import { uniqueComments, useCommentsQuery, useCommentLocationQuery, type Comment, type CommentSort } from "@/entities/comment";
import { CommentComposer, CommentControls, type useCommentDrafts, type CommentFormValues } from "@/features/work-comments";
import { isApiError } from "@/shared/api/client";

import { resolveSavedTarget, type SavedTargetOverride } from "../model/interactionState";
import { CommentThread } from "./CommentThread";
import { CreatorCommentTools } from "./CreatorCommentTools";

type ContentCommentsViewProps = {
  contentId: string; targetCommentId?: string; viewerId: string; isLoggedIn: boolean;
  draftState: ReturnType<typeof useCommentDrafts>;
};

export function ContentCommentsView({ contentId, targetCommentId, viewerId, isLoggedIn, draftState }: ContentCommentsViewProps) {
  const [sort, setSort] = useState<CommentSort>("latest");
  const replyId = draftState.activeReplyId;
  const setReplyId = draftState.selectReplyDraft;
  const editId = draftState.activeEditId;
  const setEditId = draftState.selectEditDraft;
  const [savedTargetOverride, setSavedTargetOverride] = useState<SavedTargetOverride>();
  if (savedTargetOverride && savedTargetOverride.sourceTargetId !== targetCommentId) setSavedTargetOverride(undefined);
  const { drafts, ensureDraft, changeDraft, finishDraft } = draftState;
  const rootQuery = useCommentsQuery(contentId, viewerId, sort);
  const targetId = resolveSavedTarget(savedTargetOverride, targetCommentId);
  const location = useCommentLocationQuery(contentId, viewerId, targetId);
  const replyLocation = useCommentLocationQuery(contentId, viewerId, replyId);
  const isInaccessible = rootQuery.isError && isApiError(rootQuery.error) && rootQuery.error.status === 404;
  const meta = isInaccessible ? undefined : rootQuery.data?.pages[0];
  const headerRef = useRef<HTMLHeadingElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const focusedTarget = useRef<string | undefined>(undefined);
  const pinned = meta?.pinnedComment?.displayState === "normal" ? meta.pinnedComment : undefined;
  const regular = isInaccessible ? [] : rootQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const located = location.isError && isApiError(location.error) && location.error.status === 404 ? undefined : location.data;
  const locatedRoot = isInaccessible ? undefined : located?.root;
  const items = uniqueComments([
    ...(pinned ? [pinned] : []), ...(locatedRoot ? [locatedRoot] : []), ...regular,
  ]).filter((comment) => comment.displayState !== "creator-hidden" && comment.displayState !== "moderator-hidden" &&
    (comment.displayState === "normal" || comment.replyCount > 0));
  const key = replyId ? "reply:" + replyId : "root";
  const draft = drafts[key];
  const reply = replyLocation.isError || isInaccessible ? undefined : replyLocation.data?.target;
  const canSubmit = !!meta?.canCreate && (!replyId || !!reply?.canReply);

  useEffect(() => { focusedTarget.current = undefined; }, [targetId, viewerId]);
  const handleFocusTarget = useCallback((id: string) => {
    if (!targetId || focusedTarget.current === targetId) return;
    const element = document.getElementById("comment-" + id);
    if (!element) return;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    focusedTarget.current = targetId;
  }, [targetId]);
  function handleFocusFallback() { headerRef.current?.focus(); }
  function handleSelectReply(comment: Comment) {
    const nextKey = "reply:" + comment.id;
    ensureDraft(nextKey);
    setReplyId(comment.id);
    requestAnimationFrame(() => composerRef.current?.querySelector("textarea")?.focus());
  }
  function handleSelectEdit(comment: Comment) { ensureDraft("edit:" + comment.id, comment); setEditId(comment.id); }
  function handleSaved(comment: Comment, draftKey: string, requestId: string, isCleared: boolean) {
    if (isCleared) finishDraft(draftKey, requestId);
    setSavedTargetOverride({ sourceTargetId: targetCommentId, commentId: comment.id });
    toast.success(isCleared ? "댓글을 저장했어요." : "댓글을 저장했어요. 전송 중 추가한 입력은 남아 있어요.");
  }
  function controls(comment: Comment, isBodyRevealed = true) {
    return <CommentControls comment={comment} viewerId={viewerId} isLoggedIn={isLoggedIn} isBodyRevealed={isBodyRevealed}
      onReply={() => handleSelectReply(comment)} onEdit={() => handleSelectEdit(comment)} onFocusFallback={handleFocusFallback} />;
  }
  function editor(comment: Comment) {
    const editKey = "edit:" + comment.id;
    const editDraft = drafts[editKey];
    if (comment.id !== editId || comment.displayState !== "normal" || !editDraft) return null;
    return <CommentComposer contentId={contentId} viewerId={viewerId} isLoggedIn={isLoggedIn}
      draft={editDraft} editCommentId={comment.id} hasInheritedSpoiler={comment.inheritedSpoiler}
      canSubmit={comment.canEdit} canAddMentions={!!meta?.canParticipate} autoFocus onCancel={() => { setEditId(undefined); handleFocusFallback(); }}
      onChange={(values: CommentFormValues) => changeDraft(editKey, values)}
      onSaved={(updated, requestId, isCleared) => handleSaved(updated, editKey, requestId, isCleared)} />;
  }

  let reason: string | undefined;
  if (meta?.commentsPaused) reason = "작가가 새 댓글 작성을 중지했어요.";
  else if (meta && isLoggedIn && !meta.canParticipate) reason = "비공개 작품은 기존 댓글 관리만 할 수 있어요.";
  else if (replyId && replyLocation.isError) reason = "답글 대상을 현재 이용할 수 없어요. 입력은 그대로 남아 있어요.";
  else if (replyId && !reply) reason = "답글 대상을 확인하는 중이에요.";

  return (
    <section aria-labelledby={"comments-heading-" + contentId} className="mt-8 flex min-w-0 flex-col gap-5 border-t border-border pt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 ref={headerRef} id={"comments-heading-" + contentId} tabIndex={-1}
          className="text-lg font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          댓글{meta && !rootQuery.isFetching ? " " + meta.visibleCommentCount : ""}
        </h2>
        <ToggleGroup type="single" variant="outline" size="sm" value={sort} aria-label="댓글 정렬"
          onValueChange={(value) => { if (value === "latest" || value === "popular") setSort(value); }}>
          <ToggleGroupItem value="latest">최신순</ToggleGroupItem><ToggleGroupItem value="popular">인기순</ToggleGroupItem>
        </ToggleGroup>
      </div>
      {!!meta?.canManage && <CreatorCommentTools contentId={contentId} viewerId={viewerId} isPaused={meta.commentsPaused}
        hiddenCount={meta.hiddenCommentCount ?? 0} onFocusFallback={handleFocusFallback} />}
      <div ref={composerRef}>
        {!!draft && <CommentComposer key={key} contentId={contentId} viewerId={viewerId} isLoggedIn={isLoggedIn}
          draft={draft} replyTarget={reply} isReplyMode={!!replyId} canSubmit={canSubmit} disabledReason={reason}
          onCancel={() => setReplyId(undefined)} onChange={(values) => changeDraft(key, values)}
          onSaved={(comment, requestId, isCleared) => handleSaved(comment, key, requestId, isCleared)} />}
      </div>
      {!!targetId && location.isPending && <p role="status" className="text-xs text-muted-foreground">해당 댓글 위치를 찾는 중…</p>}
      {!!targetId && location.isError && <div>
        <p role="alert" className="break-keep text-sm text-muted-foreground">현재 작품이나 댓글 상태에서 해당 댓글을 이용할 수 없어요. 이전 내용은 표시하지 않아요.</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void location.refetch()}>위치 다시 찾기</Button>
      </div>}
      <ContentCommentsList query={rootQuery} isInaccessible={isInaccessible} items={items} renderRoot={(root) => (
        <CommentThread key={root.id} root={root} contentId={contentId} viewerId={viewerId}
          location={located?.root.id === root.id ? located : undefined}
          targetId={located?.root.id === root.id ? targetId : undefined} onTargetReady={handleFocusTarget}
          renderControls={controls} renderEditor={editor} />
      )} />
    </section>
  );
}


type ContentCommentsListProps = {
  query: ReturnType<typeof useCommentsQuery>; isInaccessible: boolean; items: Comment[]; renderRoot: (comment: Comment) => ReactNode;
};

function ContentCommentsList({ query, isInaccessible, items, renderRoot }: ContentCommentsListProps) {
  function handleRetry() { if (query.isFetchNextPageError) void query.fetchNextPage(); else void query.refetch(); }
  const error = <div className="flex flex-col items-start gap-2">
    <p role="alert" className="break-keep text-sm text-destructive-text">{isInaccessible ? "현재 이 작품의 댓글을 이용할 수 없어요. 작성 중인 입력은 유지돼요." : "댓글을 불러오지 못했어요. 이미 읽은 댓글과 입력은 유지돼요."}</p>
    <Button type="button" variant="outline" onClick={handleRetry}>다시 시도</Button>
  </div>;
  if (query.isPending) return <p role="status" className="text-sm text-muted-foreground">댓글을 불러오는 중…</p>;
  if (query.isError && (!query.data || isInaccessible)) return error;
  if (!query.isError && items.length === 0 && !query.hasNextPage) return <p className="py-4 text-sm text-muted-foreground">첫 감상을 남겨보세요.</p>;
  return <>
    {query.isError && error}
    <div className="min-w-0">{items.map(renderRoot)}</div>
    {query.hasNextPage && <Button type="button" variant="outline" className="w-fit aria-disabled:opacity-65"
      aria-disabled={query.isFetchingNextPage} onClick={() => { if (!query.isFetchingNextPage) void query.fetchNextPage(); }}>
      {query.isFetchingNextPage ? "불러오는 중…" : "댓글 더 보기"}
    </Button>}
  </>;
}
