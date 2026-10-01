import { useEffect, useId, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { COMMENT_GHOST_HOVER_CLASS_NAME, CommentRow, uniqueComments, useCommentRepliesQuery, type Comment, type CommentLocation } from "@/entities/comment";
import { isApiError } from "@/shared/api/client";

import { resolveThreadExpanded, type ThreadExpansionOverride } from "../model/interactionState";
import { CommentReplyRow } from "./CommentReplyRow";

type CommentThreadProps = {
  root: Comment; contentId: string; viewerId: string; location?: CommentLocation;
  renderControls: (comment: Comment, isBodyRevealed: boolean) => ReactNode; renderEditor: (comment: Comment) => ReactNode;
  targetId?: string; onTargetReady: (id: string) => void;
};

export function CommentThread({
  root, contentId, viewerId, location, renderControls, renderEditor, targetId, onTargetReady,
}: CommentThreadProps) {
  const id = useId();
  const [expansionOverride, setExpansionOverride] = useState<ThreadExpansionOverride>();
  const [revealedVersion, setRevealedVersion] = useState<string>();
  const version = root.updatedAt + ":" + root.effectiveSpoiler;
  const isRevealed = !root.effectiveSpoiler || revealedVersion === version;
  const anchor = location?.replies ? location.target.id : undefined;
  if (expansionOverride && expansionOverride.anchor !== anchor) setExpansionOverride(undefined);
  const isExpanded = resolveThreadExpanded(expansionOverride, anchor, !!location?.replies);
  const replies = useCommentRepliesQuery(contentId, viewerId, root.id, isExpanded && isRevealed, anchor, location?.replies ?? undefined);
  const isInaccessible = replies.isError && isApiError(replies.error) && replies.error.status === 404;
  const items = uniqueComments(isInaccessible ? [] : replies.data?.pages.flatMap((page) => page.items) ?? []);

  useEffect(() => {
    if (!targetId) return;
    if (!isRevealed || targetId === root.id) onTargetReady(root.id);
    else if (isExpanded && items.some((comment) => comment.id === targetId)) onTargetReady(targetId);
  }, [targetId, root.id, isRevealed, isExpanded, items, onTargetReady]);

  return (
    <div className="border-b border-border last:border-b-0">
      <CommentRow comment={root} isRevealed={isRevealed} onReveal={() => setRevealedVersion(version)}
        isHighlighted={targetId === root.id || (!isRevealed && !!location)} editor={renderEditor(root)}>
        {renderControls(root, isRevealed)}
        {root.replyCount > 0 && <Button type="button" variant="ghost" size="sm" className={cn("w-fit", COMMENT_GHOST_HOVER_CLASS_NAME)}
          aria-expanded={isExpanded} aria-controls={id} onClick={() => setExpansionOverride({ anchor, isExpanded: !isExpanded })}>
          답글 {root.replyCount}개 {isExpanded ? "접기" : "보기"}
        </Button>}
      </CommentRow>
      {isExpanded && !isRevealed && <p className="pb-4 pl-4 text-xs text-muted-foreground">스포일러 보기를 누르면 이 스레드의 답글을 읽을 수 있어요.</p>}
      {isExpanded && isRevealed && <div id={id} className="ml-3 min-w-0 border-l border-border pl-3 sm:ml-6 sm:pl-4">
        <CommentRepliesList replies={replies} items={items} renderReply={(comment) => (
          <CommentReplyRow key={comment.id} comment={comment} isInheritedRevealed={root.effectiveSpoiler && isRevealed}
            isHighlighted={targetId === comment.id} renderControls={(isBodyRevealed) => renderControls(comment, isBodyRevealed)} editor={renderEditor(comment)} />
        )} />
      </div>}
    </div>
  );
}


type CommentRepliesListProps = {
  replies: ReturnType<typeof useCommentRepliesQuery>; items: Comment[]; renderReply: (comment: Comment) => ReactNode;
};

function CommentRepliesList({ replies, items, renderReply }: CommentRepliesListProps) {
  function handleRetry() {
    if (replies.isFetchPreviousPageError) void replies.fetchPreviousPage();
    else if (replies.isFetchNextPageError) void replies.fetchNextPage();
    else void replies.refetch();
  }
  const error = <div className="py-3">
    <p className="break-keep text-xs text-destructive-text">답글을 불러오지 못했어요. 이미 읽은 답글은 유지돼요.</p>
    <Button type="button" variant="outline" size="sm" onClick={handleRetry}>다시 시도</Button>
  </div>;
  if (replies.isPending) return <p className="py-4 text-xs text-muted-foreground" role="status">답글을 불러오는 중…</p>;
  if (replies.isError && !replies.data) return error;
  if (!replies.isError && items.length === 0 && !replies.hasNextPage && !replies.hasPreviousPage) return <p className="py-3 text-xs text-muted-foreground">표시할 답글이 없어요.</p>;
  return <>
    {replies.hasPreviousPage && <Button type="button" variant="outline" size="sm" aria-disabled={replies.isFetchingPreviousPage}
      className="my-2 aria-disabled:opacity-65" onClick={() => { if (!replies.isFetchingPreviousPage) void replies.fetchPreviousPage(); }}>이전 답글 더 보기</Button>}
    {items.map(renderReply)}
    {replies.isError && error}
    {replies.hasNextPage && <Button type="button" variant="outline" size="sm" className="my-3 aria-disabled:opacity-65"
      aria-disabled={replies.isFetchingNextPage} onClick={() => { if (!replies.isFetchingNextPage) void replies.fetchNextPage(); }}>답글 더 보기</Button>}
  </>;
}
