import { Link } from "@tanstack/react-router";

import { type NoticeListItem, useNoticeListQuery } from "@/entities/notice";
import { formatDate } from "@/shared/lib/time/formatDate";

/** `/notices` — 공지사항 목록. 로그인 여부와 무관하게 접근 가능(D-5). 제목은 쿼리와 무관하게
 * 상시 렌더하고 본문만 로딩·에러·빈 상태로 가른다(`pages/legal-document`의 관용구). */
export function NoticesPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">공지사항</h1>
      <NoticeListBody />
    </main>
  );
}

function NoticeListBody() {
  const noticeListQuery = useNoticeListQuery();

  if (noticeListQuery.isPending) {
    return <NoticeListSkeleton />;
  }

  if (noticeListQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        공지사항을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (noticeListQuery.data.items.length === 0) {
    return <p className="py-16 text-center text-sm text-muted-foreground">아직 등록된 공지가 없어요.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {noticeListQuery.data.items.map((item) => (
        <NoticeListItemRow key={item.id} item={item} />
      ))}
    </div>
  );
}

function NoticeListItemRow({ item }: { item: NoticeListItem }) {
  return (
    <Link
      to="/notices/$noticeId"
      params={{ noticeId: item.id }}
      className="flex flex-col gap-1 rounded-xl border border-border bg-background p-4 outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
    >
      <span className="break-keep text-base font-semibold text-foreground">{item.title}</span>
      <span className="text-sm text-muted-foreground">{formatDate(item.publishedAt)}</span>
    </Link>
  );
}

function NoticeListSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
    </div>
  );
}
