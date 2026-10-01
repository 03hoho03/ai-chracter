import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";

import { CommentRow, uniqueComments, useHiddenCommentsQuery } from "@/entities/comment";
import { CommentActionModal, CommentControls, usePauseCommentsMutation } from "@/features/work-comments";

type CreatorCommentToolsProps = {
  contentId: string; viewerId: string; isPaused: boolean; hiddenCount: number; onFocusFallback: () => void;
};

export function CreatorCommentTools({ contentId, viewerId, isPaused, hiddenCount, onFocusFallback }: CreatorCommentToolsProps) {
  const [shouldShowHidden, setShouldShowHidden] = useState(false);
  const pauseRef = useRef<HTMLButtonElement>(null);
  const hidden = useHiddenCommentsQuery(contentId, viewerId, shouldShowHidden);
  const pause = usePauseCommentsMutation(contentId, viewerId);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button ref={pauseRef} type="button" variant="outline" size="sm" aria-disabled={pause.isPending}
          className="aria-disabled:opacity-65" onClick={() => {
            if (pause.isPending) return;
            void CommentActionModal.call({
              title: isPaused ? "새 댓글 작성을 다시 열까요?" : "새 댓글 작성을 중지할까요?",
              description: isPaused ? "독자가 새 댓글과 답글을 남길 수 있어요." : "기존 댓글은 유지되고 작가 본인을 포함해 새 댓글과 답글을 남길 수 없어요.",
              confirmLabel: isPaused ? "다시 열기" : "작성 중지",
              returnFocus: () => pauseRef.current?.isConnected ? pauseRef.current.focus() : onFocusFallback(),
              mutationFn: async (call) => { try { await pause.mutateAsync(!isPaused); call.end(); } catch { /* The mutation shows the error. */ } },
            });
          }}>{isPaused ? "새 댓글 작성 재개" : "새 댓글 작성 중지"}</Button>
        <Button type="button" variant="ghost" size="sm" className="in-data-[slot=dialog-content]:hover:bg-secondary" aria-expanded={shouldShowHidden}
          onClick={() => setShouldShowHidden((current) => !current)}>숨긴 댓글 관리 {hiddenCount > 0 && "(" + hiddenCount + ")"}</Button>
      </div>
      {shouldShowHidden && <div className="rounded-lg border border-border p-3">
        <p className="break-keep text-xs text-muted-foreground">작가 숨김만 해제할 수 있어요. 삭제된 원댓글은 내용이 돌아오지 않고 남은 답글의 숨김만 해제돼요. 운영 숨김과 답글별 숨김은 유지돼요.</p>
        <CreatorHiddenCommentsList query={hidden} viewerId={viewerId} onFocusFallback={onFocusFallback} />
      </div>}
    </div>
  );
}


type CreatorHiddenCommentsListProps = {
  query: ReturnType<typeof useHiddenCommentsQuery>; viewerId: string; onFocusFallback: () => void;
};

function CreatorHiddenCommentsList({ query, viewerId, onFocusFallback }: CreatorHiddenCommentsListProps) {
  const items = uniqueComments(query.data?.pages.flatMap((page) => page.items) ?? []);
  function handleRetry() { if (query.isFetchNextPageError) void query.fetchNextPage(); else void query.refetch(); }
  const error = <div><p className="text-xs text-destructive-text">숨긴 댓글을 불러오지 못했어요.</p><Button type="button" variant="outline" size="sm" onClick={handleRetry}>다시 시도</Button></div>;
  if (query.isPending) return <p className="py-3 text-xs" role="status">숨긴 댓글을 불러오는 중…</p>;
  if (query.isError && !query.data) return error;
  if (!query.isError && items.length === 0 && !query.hasNextPage) return <p className="py-3 text-xs text-muted-foreground">작가가 숨긴 댓글이 없어요.</p>;
  return <>
    {items.map((comment) => <CommentRow key={comment.id} comment={comment} isRevealed onReveal={() => {}}>
      <span className="text-xs text-muted-foreground">{comment.id.slice(0, 8)}{comment.moderatorHidden && " · 운영 숨김도 적용됨"}</span>
      <CommentControls comment={comment} viewerId={viewerId} isLoggedIn onEdit={() => {}} onReply={() => {}} onFocusFallback={onFocusFallback} />
    </CommentRow>)}
    {query.isError && error}
    {query.hasNextPage && <Button type="button" variant="outline" size="sm" aria-disabled={query.isFetchingNextPage}
      onClick={() => { if (!query.isFetchingNextPage) void query.fetchNextPage(); }}>숨긴 댓글 더 보기</Button>}
  </>;
}
