import { useRef, type RefObject } from "react";
import { Button } from "@ai-character-chat/ui/components/button";

import { uniqueComments, useCommentMutesQuery } from "@/entities/comment";

import { useUnmuteCommentUserMutation } from "../api/useUnmuteCommentUserMutation";
import { CommentActionModal } from "./CommentActionModal";

export function CommentMutedUsers({ viewerId }: { viewerId: string }) {
  const headerRef = useRef<HTMLHeadingElement>(null);
  const query = useCommentMutesQuery(viewerId, true);
  const restore = useUnmuteCommentUserMutation(viewerId);
  return <div className="flex flex-col gap-3 pt-3">
    <h3 ref={headerRef} tabIndex={-1} className="text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50">숨긴 사용자</h3>
    <CommentMutedUsersList query={query} restore={restore} headerRef={headerRef} />
  </div>;
}


type CommentMutedUsersListProps = {
  query: ReturnType<typeof useCommentMutesQuery>; restore: ReturnType<typeof useUnmuteCommentUserMutation>;
  headerRef: RefObject<HTMLHeadingElement | null>;
};

function CommentMutedUsersList({ query, restore, headerRef }: CommentMutedUsersListProps) {
  const items = uniqueComments(query.data?.pages.flatMap((page) => page.items) ?? []);
  function handleRetry() { if (query.isFetchNextPageError) void query.fetchNextPage(); else void query.refetch(); }
  const error = <div><p role="alert" className="text-sm text-destructive-text">숨긴 사용자를 불러오지 못했어요.</p>
    <Button type="button" variant="outline" size="sm" onClick={handleRetry}>다시 시도</Button></div>;
  if (query.isPending) return <p role="status" className="text-sm text-muted-foreground">숨긴 사용자를 불러오는 중…</p>;
  if (query.isError && !query.data) return error;
  if (!query.isError && items.length === 0 && !query.hasNextPage) return <p className="text-sm text-muted-foreground">숨긴 사용자가 없어요.</p>;
  return <>
    {items.map((author) => <div key={author.id} className="flex min-w-0 items-center justify-between gap-3">
      <span className="min-w-0 break-all text-sm">{author.nickname}<span className="ml-2 text-xs text-muted-foreground">{author.id.slice(0, 8)}</span></span>
      <Button type="button" variant="outline" size="sm" aria-disabled={restore.isPending} className="shrink-0 aria-disabled:opacity-65"
        onClick={(event) => {
          if (restore.isPending) return;
          const button = event.currentTarget;
          void CommentActionModal.call({ title: "이 사용자의 댓글 숨김을 해제할까요?", description: "현재 읽을 수 있는 댓글과 댓글 알림을 다시 볼 수 있어요.",
            confirmLabel: "숨김 해제", returnFocus: () => { if (button.isConnected) button.focus(); else headerRef.current?.focus(); },
            mutationFn: async (call) => { try { await restore.mutateAsync(author.id); call.end(); } catch { /* Keep retry available. */ } },
          });
        }}>숨김 해제</Button>
    </div>)}
    {query.isError && error}
    {query.hasNextPage && <Button type="button" variant="outline" size="sm" className="w-fit aria-disabled:opacity-65" aria-disabled={query.isFetchingNextPage}
      onClick={() => { if (!query.isFetchingNextPage) void query.fetchNextPage(); }}>숨긴 사용자 더 보기</Button>}
  </>;
}
