import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@ai-character-chat/ui/components/sheet";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { Flag, MoreHorizontal, Trash2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useMedia } from "react-use";
import { toast } from "sonner";

import { useWebnovelCommentsQuery, type WebnovelComment } from "@/entities/webnovel";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { useCreateWebnovelCommentMutation, useDeleteWebnovelCommentMutation } from "../api/useWebnovelCommentMutations";
import { countVisibleCharacters, toCommentWriteError, WEBNOVEL_COMMENT_MAX_LENGTH } from "../model/commentFailure";

type WebnovelCommentsSheetProps = {
  novelId: string;
  chapterId: string;
  /** 머리에 붙일 화 이름("7화"). */
  episodeLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 닫힌 뒤 포커스를 돌려줄 요소(연 자리가 위 바·화 끝 둘이다). */
  returnFocusTo: () => HTMLElement | null;
  /** 남의 댓글 신고 — 신고 모달은 다른 기능이라 화면이 넣는다. */
  onReport: (commentId: string) => void;
};

/** 노벨 화 댓글 — 판형 흐름 밖의 시트라 댓글 수가 쪽 수를 바꾸지 않는다. `md` 미만은 아래 시트(최대 화면 85%, 위
 * 모서리 둥금), 이상은 오른쪽 시트다. 머리 "7화 댓글 12 · 최신순", 목록(이니셜 · 닉네임 · 게시자 표식 · 시각 · 본문 ·
 * 내 글·게시자면 지우기, 남의 글이면 신고), 아래 입력칸과 [등록].
 *
 * 볼 수 있는 화(무료·소장·게시자 본인)에서만 열리므로 입력칸이 늘 있다. 시트가 `popover` 표면이라 hover 채움은
 * `secondary` 다. 등장·퇴장은 `Sheet` 프리미티브의 모션 가드를 따른다. */
export function WebnovelCommentsSheet({
  novelId,
  chapterId,
  episodeLabel,
  open,
  onOpenChange,
  returnFocusTo,
  onReport,
}: WebnovelCommentsSheetProps) {
  const isWide = useMedia("(min-width: 768px)");
  const contentRef = useRef<HTMLDivElement>(null);
  const descriptionId = useId();
  const query = useWebnovelCommentsQuery(novelId, chapterId);
  const total = query.data?.pages[0]?.totalCount;
  const comments = query.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={isWide ? "right" : "bottom"}
        ref={contentRef}
        aria-describedby={descriptionId}
        // 열 때 첫 조작(첫 댓글의 ⋯)이 아니라 시트 자체에 포커스를 둔다 — 읽으러 연 것이지 그 댓글을 고르려고 연 것이
        // 아니고, 입력칸에 두면 폰에서 키보드가 바로 올라와 목록을 덮는다. 다음 Tab 이 목록부터 간다.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          contentRef.current?.focus();
        }}
        className="max-h-[85dvh] rounded-t-2xl data-[side=right]:max-h-none data-[side=right]:w-full data-[side=right]:rounded-none data-[side=right]:sm:max-w-md"
        onCloseAutoFocus={(event) => {
          const target = returnFocusTo();
          if (target === null || !target.isConnected || target.closest("[inert]") !== null) return;
          event.preventDefault();
          target.focus();
        }}
      >
        {/* 오른쪽 위 닫기(X)와 겹치지 않게 머리 오른쪽을 비운다. */}
        <SheetHeader className="pr-14">
          <SheetTitle className="tabular-nums">
            {episodeLabel} 댓글{total === undefined ? "" : ` ${total.toLocaleString()}`}
          </SheetTitle>
          <SheetDescription id={descriptionId} className="text-xs text-muted-foreground">
            최신순
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4">
          <CommentList novelId={novelId} chapterId={chapterId} query={query} comments={comments} onReport={onReport} />
        </div>

        <CommentComposer novelId={novelId} chapterId={chapterId} />
      </SheetContent>
    </Sheet>
  );
}

function CommentList({
  novelId,
  chapterId,
  query,
  comments,
  onReport,
}: {
  novelId: string;
  chapterId: string;
  query: ReturnType<typeof useWebnovelCommentsQuery>;
  comments: WebnovelComment[];
  onReport: (commentId: string) => void;
}) {
  const remove = useDeleteWebnovelCommentMutation(novelId, chapterId);
  const now = new Date();

  if (query.isPending) {
    // 진행 표시라 동작 줄이기 설정에서도 돈다.
    return (
      <div aria-hidden className="flex flex-col gap-4 py-2">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex gap-3">
            <div className="size-8 shrink-0 animate-pulse rounded-full bg-secondary" />
            <div className="flex flex-1 flex-col gap-2">
              <div className="h-4 w-24 animate-pulse rounded bg-secondary" />
              <div className="h-4 w-full animate-pulse rounded bg-secondary" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (query.isError && comments.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2 py-6 text-sm text-muted-foreground">
        <p>댓글을 불러오지 못했어요.</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  if (comments.length === 0) {
    return <p className="py-10 text-center text-sm text-muted-foreground">첫 댓글을 남겨 주세요.</p>;
  }

  async function handleDelete(commentId: string) {
    try {
      await remove.mutateAsync(commentId);
      toast.success("댓글을 지웠어요.");
    } catch {
      toast.error("댓글을 지우지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
  }

  return (
    <div className="flex flex-col pb-2">
      <ul className="flex flex-col divide-y divide-border">
        {comments.map((comment) => (
          <li key={comment.id} className="flex gap-3 py-3">
            <span
              aria-hidden
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-medium text-muted-foreground"
            >
              {(comment.authorNickname ?? "?").slice(0, 1)}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                <span className="truncate font-medium text-foreground">{comment.authorNickname ?? "알 수 없는 회원"}</span>
                {comment.isPublisher && (
                  <span className="shrink-0 rounded-full border border-border px-1.5 text-badge font-medium">게시자</span>
                )}
                <span className="shrink-0">·</span>
                <time dateTime={comment.createdAt} className="shrink-0">
                  {formatRelativeTime(comment.createdAt, now)}
                </time>
              </div>
              <p className="text-sm whitespace-pre-line text-pretty break-keep wrap-anywhere text-foreground">{comment.body}</p>
            </div>
            {(comment.canDelete || comment.canReport) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="댓글 더보기"
                    className="-mr-1 shrink-0 hover:bg-secondary aria-expanded:bg-secondary"
                  >
                    <MoreHorizontal aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto">
                  {comment.canDelete && (
                    <DropdownMenuItem onSelect={() => void handleDelete(comment.id)}>
                      <Trash2 aria-hidden />
                      지우기
                    </DropdownMenuItem>
                  )}
                  {comment.canReport && (
                    <DropdownMenuItem onSelect={() => onReport(comment.id)}>
                      <Flag aria-hidden />
                      신고하기
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </li>
        ))}
      </ul>
      {query.hasNextPage && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={query.isFetchingNextPage}
          className="self-center hover:bg-secondary aria-disabled:opacity-65"
          onClick={() => {
            if (query.isFetchingNextPage) return;
            void query.fetchNextPage();
          }}
        >
          {query.isFetchingNextPage ? "불러오는 중…" : "댓글 더 보기"}
        </Button>
      )}
    </div>
  );
}

/** 입력칸과 [등록]. 실패하면 쓴 글을 그대로 두고 밑에 까닭을 말한다. 글자 수는 상한 가까이에서만 보인다. */
function CommentComposer({ novelId, chapterId }: { novelId: string; chapterId: string }) {
  const inputId = useId();
  const errorId = useId();
  const create = useCreateWebnovelCommentMutation(novelId, chapterId);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);
  const length = countVisibleCharacters(body);
  const isOver = length > WEBNOVEL_COMMENT_MAX_LENGTH;

  async function handleSubmit() {
    if (create.isPending) return;
    if (body.trim() === "") {
      setError("댓글 내용을 입력해 주세요.");
      return;
    }
    if (isOver) {
      setError("댓글은 1,000자까지 쓸 수 있어요.");
      return;
    }
    setError(undefined);
    try {
      await create.mutateAsync(body);
      setBody("");
    } catch (writeError) {
      setError(toCommentWriteError(writeError));
    }
  }

  return (
    <form
      noValidate
      className="flex flex-col gap-2 border-t border-border p-4 pb-4-safe"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      <label htmlFor={inputId} className="sr-only">
        댓글 쓰기
      </label>
      <Textarea
        id={inputId}
        value={body}
        rows={2}
        placeholder="이 화에 대한 생각을 남겨 주세요"
        aria-invalid={error !== undefined || isOver}
        aria-describedby={error !== undefined ? errorId : undefined}
        className="max-h-40"
        onChange={(event) => setBody(event.target.value)}
      />
      <div className="flex items-center justify-between gap-2">
        <p id={errorId} role={error !== undefined ? "alert" : undefined} className="min-w-0 text-xs break-keep text-destructive-text">
          {error}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          {length > WEBNOVEL_COMMENT_MAX_LENGTH - 100 && (
            <span className={isOver ? "text-xs text-destructive-text tabular-nums" : "text-xs text-muted-foreground tabular-nums"}>
              {length.toLocaleString()}/{WEBNOVEL_COMMENT_MAX_LENGTH.toLocaleString()}
            </span>
          )}
          <Button type="submit" size="sm" aria-disabled={create.isPending} className="aria-disabled:opacity-65">
            {create.isPending ? "남기는 중…" : "등록"}
          </Button>
        </div>
      </div>
    </form>
  );
}
