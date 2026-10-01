import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Pin } from "lucide-react";

import type { Comment } from "../model/comment";
import { CommentStickerImage } from "./CommentStickerImage";
import { CommentBody } from "./CommentBody";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" });
const STATE_LABELS = {
  deleted: "삭제된 댓글", muted: "숨긴 사용자의 댓글",
  "creator-hidden": "작가가 숨긴 댓글", "moderator-hidden": "운영자가 숨긴 댓글",
};

type CommentRowProps = {
  comment: Comment; isRevealed: boolean; onReveal: () => void; isHighlighted?: boolean;
  children?: ReactNode; editor?: ReactNode;
};

export function CommentRow({
  comment, isRevealed, onReveal, isHighlighted = false, children, editor,
}: CommentRowProps) {
  const isHidden = comment.displayState !== "normal";
  const isBodyProtected = comment.effectiveSpoiler && !isRevealed;
  return (
    <article id={"comment-" + comment.id} tabIndex={-1} data-comment-highlighted={isHighlighted || undefined}
      aria-label={isHighlighted ? "알림 대상 댓글" : undefined}
      className={cn("min-w-0 scroll-mt-24 rounded-lg py-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        isHighlighted && "bg-secondary px-3 ring-1 ring-border")}>
      <div className="flex min-w-0 items-start gap-2.5">
        {!isHidden && !!comment.author?.profileImageUrl && (
          <img src={comment.author.profileImageUrl} alt="" width={32} height={32}
            loading="lazy" decoding="async" className="size-8 shrink-0 rounded-full object-cover" />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {!isHidden && !!comment.author && (
              <Link to="/profile/$userId" params={{ userId: comment.author.id }}
                className="min-w-0 break-all font-semibold text-foreground hover:underline focus-visible:underline">
                {comment.author.nickname}
              </Link>
            )}
            {!isHidden && !!comment.author?.isCreator && <span className="rounded bg-secondary px-1.5 py-0.5 text-badge text-secondary-foreground">작가</span>}
            {comment.isPinned && <span className="inline-flex items-center gap-1"><Pin aria-hidden className="size-3" />고정</span>}
            <time dateTime={comment.createdAt}>{dateFormatter.format(new Date(comment.createdAt))}</time>
            {comment.isEdited && <span>수정됨</span>}
          </div>
          {comment.displayState !== "normal" && <p className="text-sm text-muted-foreground">{STATE_LABELS[comment.displayState]}</p>}
          {isBodyProtected && (!isHidden || comment.replyCount > 0) && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">스포일러가 포함된 댓글이에요.</span>
              <Button type="button" variant="outline" size="sm" onClick={onReveal}>스포일러 보기</Button>
            </div>
          )}
          {!isHidden && !isBodyProtected && !editor && (
            <>
              {!!comment.replyTo && (
                <p className="line-clamp-2 break-keep text-xs text-muted-foreground">
                  {comment.replyTo.author ? comment.replyTo.author.nickname + "님에게 답글" : "삭제·숨김된 댓글에 대한 답글"}
                  {!comment.replyTo.effectiveSpoiler && !!comment.replyTo.bodyPreview && " · " + comment.replyTo.bodyPreview}
                </p>
              )}
              {comment.mentions.length > 0 && (
                <p className="flex flex-wrap gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  {comment.mentions.map((author) => <span key={author.id}>@{author.nickname}</span>)}
                </p>
              )}
              {!!comment.body && <CommentBody key={comment.updatedAt ?? comment.createdAt} body={comment.body} />}
              {!!comment.sticker && <CommentStickerImage sticker={comment.sticker} />}
            </>
          )}
          {!isBodyProtected && editor}
          {children}
        </div>
      </div>
    </article>
  );
}
