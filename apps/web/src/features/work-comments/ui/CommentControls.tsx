import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@ai-character-chat/ui/components/dropdown-menu";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Heart, MoreHorizontal } from "lucide-react";
import { useDebounce } from "react-use";
import { toast } from "sonner";

import type { Comment } from "@/entities/comment";

import { useCommentActionMutation, type CommentAction } from "../api/useCommentActionMutation";
import { useLikeCommentMutation } from "../api/useLikeCommentMutation";
import { CommentActionModal } from "./CommentActionModal";
import { CommentLoginModal } from "./CommentLoginModal";
import { CommentReportModal } from "./CommentReportModal";

type CommentControlsProps = {
  comment: Comment; viewerId: string; isLoggedIn: boolean; onReply: () => void; onEdit: () => void; onFocusFallback: () => void;
  isBodyRevealed?: boolean;
};

export function CommentControls({
  comment, viewerId, isLoggedIn, onReply, onEdit, onFocusFallback, isBodyRevealed = true,
}: CommentControlsProps) {
  const menuRef = useRef<HTMLButtonElement>(null);
  const shouldSkipMenuRestore = useRef(false);
  const [isLikedOverride, setIsLikedOverride] = useState<boolean>();
  const isNormal = comment.displayState === "normal";
  const hasMenu = isNormal || comment.canEdit || comment.canDelete || comment.canPin || comment.canCreatorHide || comment.canCreatorRestore;
  const isLiked = isLikedOverride ?? comment.isLiked;
  let likeDelta = 0;
  if (isLiked !== comment.isLiked) likeDelta = isLiked ? 1 : -1;
  const like = useLikeCommentMutation(comment.id, comment.contentId, viewerId);
  const action = useCommentActionMutation(viewerId);
  useDebounce(() => {
    if (isLikedOverride === undefined || isLikedOverride === comment.isLiked || !comment.canLike || like.isPending) return;
    const sent = isLikedOverride;
    like.mutate(sent, { onSettled: () => setIsLikedOverride((current) => current === sent ? undefined : current) });
  }, 400, [isLikedOverride, comment.isLiked, comment.canLike, like.isPending]);

  function handleReturnFocus() {
    if (menuRef.current?.isConnected) menuRef.current.focus();
    else onFocusFallback();
  }
  function handleLogin() { void CommentLoginModal.call({ returnFocus: handleReturnFocus }); }
  function handleConfirm(title: string, description: string, confirmLabel: string, operation: CommentAction, isDestructive = false) {
    if (action.isPending) return;
    void CommentActionModal.call({ title, description, confirmLabel, isDestructive, returnFocus: handleReturnFocus,
      mutationFn: async (call) => { try { await action.mutateAsync(operation); call.end(); } catch { /* Action error is shown by the mutation. */ } } });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {isNormal && <Button type="button" variant="ghost" size="sm" aria-pressed={isLiked}
        aria-label={isLiked ? "댓글 좋아요 취소" : "댓글 좋아요"}
        aria-disabled={isLoggedIn && !comment.canLike} className={cn("aria-disabled:opacity-65 in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:hover:bg-secondary in-data-[comment-highlighted=true]:hover:bg-foreground/10", isLiked && "text-primary")}
        onClick={() => {
          if (!isLoggedIn) { handleLogin(); return; }
          if (!comment.canLike) return;
          setIsLikedOverride((current) => !(current ?? comment.isLiked));
        }}>
        <Heart aria-hidden className={isLiked ? "fill-primary" : undefined} />
        {Math.max(0, comment.likeCount + likeDelta)}
      </Button>}
      {(comment.canReply || (!isLoggedIn && isNormal)) && <Button type="button" variant="ghost" size="sm" className="in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:hover:bg-secondary in-data-[comment-highlighted=true]:hover:bg-foreground/10"
        onClick={() => { if (!isLoggedIn) handleLogin(); else onReply(); }}>답글</Button>}
      {hasMenu && <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button ref={menuRef} type="button" variant="ghost" size="icon-sm" className="in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:hover:bg-secondary in-data-[comment-highlighted=true]:hover:bg-foreground/10 in-data-[slot=dialog-content]:not-in-data-[comment-highlighted=true]:data-[state=open]:bg-secondary in-data-[comment-highlighted=true]:data-[state=open]:bg-foreground/10" aria-label="댓글 메뉴"><MoreHorizontal aria-hidden /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto" collisionPadding={8}
          onCloseAutoFocus={(event) => {
            if (shouldSkipMenuRestore.current) { event.preventDefault(); shouldSkipMenuRestore.current = false; }
          }}>
          {comment.canEdit && isBodyRevealed && <DropdownMenuItem onSelect={() => { shouldSkipMenuRestore.current = true; onEdit(); }}>수정</DropdownMenuItem>}
          {comment.canDelete && <DropdownMenuItem className="text-destructive-text" onSelect={() => handleConfirm(
            "댓글을 삭제할까요?", "내용과 스티커는 제거되고 다른 사람의 답글은 남아요. 삭제한 댓글은 복원할 수 없어요.", "삭제",
            { type: "delete", commentId: comment.id },
            true,
          )}>삭제</DropdownMenuItem>}
          {comment.canPin && <DropdownMenuItem onSelect={() => {
            void action.mutateAsync({ type: "pin", contentId: comment.contentId, commentId: comment.isPinned ? undefined : comment.id }).catch(() => {});
          }}>{comment.isPinned ? "고정 해제" : "댓글 고정"}</DropdownMenuItem>}
          {comment.canCreatorHide && <DropdownMenuItem onSelect={() => handleConfirm(
            "이 댓글을 숨길까요?", comment.rootCommentId ? "모든 독자에게 이 댓글이 숨겨져요. 나중에 복원할 수 있어요." : "이 원댓글과 그 아래 답글이 모든 독자에게 숨겨져요. 나중에 복원할 수 있어요.", "숨기기",
            { type: "creator-hide", commentId: comment.id, isHidden: true, shouldHideThread: comment.rootCommentId === null },
          )}>작가 권한으로 숨기기</DropdownMenuItem>}
          {comment.canCreatorRestore && <DropdownMenuItem onSelect={() => {
            void action.mutateAsync({ type: "creator-hide", commentId: comment.id, isHidden: false }).catch(() => {});
          }}>{comment.displayState === "deleted" && comment.rootCommentId === null ? "삭제된 원댓글 숨김 해제" : "작가 숨김 복원"}</DropdownMenuItem>}
          {isNormal && <><DropdownMenuSeparator />
            {(comment.canReport || !isLoggedIn) && <DropdownMenuItem onSelect={() => {
              if (!isLoggedIn) { handleLogin(); return; }
              void CommentReportModal.call({ returnFocus: handleReturnFocus, mutationFn: async (call, reason) => {
                try {
                  await action.mutateAsync({ type: "report", commentId: comment.id, reason });
                  toast.success("신고가 접수됐어요."); call.end();
                } catch { /* The report selection remains available for retry. */ }
              } });
            }}>신고</DropdownMenuItem>}
            {comment.author?.id !== viewerId && <DropdownMenuItem onSelect={() => {
              if (!isLoggedIn) { handleLogin(); return; }
              const authorId = comment.author?.id;
              if (!authorId) return;
              handleConfirm("이 사용자의 댓글을 숨길까요?", "내 화면에서 이 사용자의 모든 댓글과 댓글 알림이 숨겨져요. 설정에서 해제할 수 있어요.", "사용자 숨기기", { type: "mute", authorId });
            }}>이 사용자의 댓글 숨기기</DropdownMenuItem>}
          </>}
        </DropdownMenuContent>
      </DropdownMenu>}
    </div>
  );
}
