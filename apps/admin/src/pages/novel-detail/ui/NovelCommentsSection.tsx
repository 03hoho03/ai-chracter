import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  NOVEL_COMMENT_DELETED_BY_LABELS,
  useNovelCommentsQuery,
  type AdminNovelComment,
} from "@/entities/admin-novel";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { NovelCommentActionConfirmModal } from "./NovelCommentActionConfirmModal";

/** 이 노벨의 댓글 전부(지운 것·숨긴 것 포함) 최신순. 쪽은 이 칸 안에서만 넘기는 지역 상태다 — 상세 URL 에 싣지 않는다. */
export function NovelCommentsSection({ novelId }: { novelId: string }) {
  const [page, setPage] = useState(1);
  const commentsQuery = useNovelCommentsQuery(novelId, page);

  return (
    <section
      aria-labelledby="novel-comments-heading"
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6"
    >
      <h2 id="novel-comments-heading" className="text-lg font-semibold text-foreground">
        댓글
      </h2>
      <QueryState
        query={commentsQuery}
        surface="card"
        errorMessage="댓글을 불러오지 못했어요."
        isEmpty={(data) => data.items.length === 0}
        empty={{ title: "아직 댓글이 없어요." }}
      >
        {(data) => (
          <>
            <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
              {data.items.map((comment) => (
                <CommentRow key={comment.id} comment={comment} />
              ))}
            </ul>
            {data.totalPages > 1 && (
              <Pagination page={data.page} totalPages={data.totalPages} totalCount={data.totalCount} onPageChange={setPage} />
            )}
          </>
        )}
      </QueryState>
    </section>
  );
}

function commentStateLabel(comment: AdminNovelComment) {
  if (comment.deletedAt !== null) {
    return `삭제됨 · ${comment.deletedBy === null ? "삭제" : `${NOVEL_COMMENT_DELETED_BY_LABELS[comment.deletedBy]}가 지움`}`;
  }
  return comment.moderatorHidden ? "운영 숨김" : "표시 중";
}

function CommentRow({ comment }: { comment: AdminNovelComment }) {
  const isDeleted = comment.deletedAt !== null;

  return (
    <li className="flex min-w-0 flex-col gap-2 px-3 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <Link
          to="/users/$userId"
          params={{ userId: comment.authorUserId }}
          className="admin-hit-area font-medium text-primary hover:underline focus-visible:underline"
        >
          {comment.authorNickname ?? "(탈퇴한 회원)"}
        </Link>
        <span>{comment.chapterOrdinal}화</span>
        <time dateTime={comment.createdAt}>{formatDateTime(comment.createdAt)}</time>
        <span className={comment.moderatorHidden || isDeleted ? "font-medium text-foreground" : undefined}>
          {commentStateLabel(comment)}
        </span>
      </div>
      {isDeleted ? (
        <p className="text-sm text-muted-foreground">지운 댓글이라 본문이 없어요.</p>
      ) : (
        <p className="max-w-prose whitespace-pre-wrap break-keep text-sm text-foreground wrap-anywhere">{comment.body}</p>
      )}
      {!isDeleted && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void NovelCommentActionConfirmModal.call({ comment, action: comment.moderatorHidden ? "restore" : "hide" })
            }
          >
            {comment.moderatorHidden ? "숨김 해제" : "숨김"}
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => void NovelCommentActionConfirmModal.call({ comment, action: "delete" })}
          >
            삭제
          </Button>
        </div>
      )}
    </li>
  );
}
