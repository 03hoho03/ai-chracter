import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { Link } from "@tanstack/react-router";
import { FileQuestion } from "lucide-react";

import { useNoticeDetailQuery } from "@/entities/notice";
import { formatDate } from "@/shared/lib/time/formatDate";

/** `/notices/$noticeId` — 공지 상세. 로그인 여부와 무관하게 접근 가능(D-5). h1이 공지 제목 자체라
 * 데이터 도착 전에는 보여줄 게 없으므로 `pages/legal-document`와 달리 제목까지 함께 상태별로 가른다. */
export function NoticeDetailPage({ noticeId }: { noticeId: string }) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <NoticeDetailBody noticeId={noticeId} />
    </main>
  );
}

function NoticeDetailBody({ noticeId }: { noticeId: string }) {
  const noticeDetailQuery = useNoticeDetailQuery(noticeId);

  if (noticeDetailQuery.isPending) {
    return <NoticeDetailSkeleton />;
  }

  if (noticeDetailQuery.isError) {
    if (noticeDetailQuery.error.status === 404) {
      return (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
          <p className="text-base font-semibold text-foreground">찾을 수 없는 공지예요</p>
          <p className="text-sm break-keep text-muted-foreground">
            삭제되었거나 잘못된 주소예요.{" "}
            <Link
              to="/notices"
              className="font-medium text-primary hover:underline focus-visible:underline"
            >
              공지사항 목록
            </Link>
            으로 돌아가세요.
          </p>
        </div>
      );
    }

    return (
      <p className="text-sm text-destructive-text">공지를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
    );
  }

  return (
    <>
      <h1 className="break-keep text-2xl font-bold tracking-tight text-foreground">
        {noticeDetailQuery.data.title}
      </h1>
      <p className="text-xs text-muted-foreground">
        게시일 {formatDate(noticeDetailQuery.data.publishedAt)}
      </p>
      <Markdown content={noticeDetailQuery.data.bodyMarkdown} />
      <Link to="/notices" className="text-sm font-medium text-primary hover:underline focus-visible:underline">
        공지사항 목록으로 돌아가기
      </Link>
    </>
  );
}

function NoticeDetailSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-7 w-2/3 animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
    </div>
  );
}
