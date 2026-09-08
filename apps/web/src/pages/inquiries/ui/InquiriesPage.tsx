import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

import {
  INQUIRY_CATEGORY_LABEL,
  INQUIRY_STATUS_BADGE_INK,
  INQUIRY_STATUS_LABEL,
  type MyInquiryListItem,
  useMyInquiryListQuery,
} from "@/entities/inquiry";
import { formatDate } from "@/shared/lib/time/formatDate";

/** `/inquiries` — 내 문의 내역. `requireSession`으로 로그인 사용자만 접근한다(D-6). */
export function InquiriesPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">내 문의 내역</h1>
      <InquiryListBody />
    </main>
  );
}

function InquiryListBody() {
  const inquiryListQuery = useMyInquiryListQuery();

  if (inquiryListQuery.isPending) {
    return <InquiryListSkeleton />;
  }

  if (inquiryListQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        문의 내역을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (inquiryListQuery.data.items.length === 0) {
    return <p className="py-16 text-center text-sm text-muted-foreground">아직 접수한 문의가 없어요.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {inquiryListQuery.data.items.map((item) => (
        <InquiryListItemRow key={item.id} item={item} />
      ))}
    </div>
  );
}

function InquiryListItemRow({ item }: { item: MyInquiryListItem }) {
  return (
    <Link
      to="/inquiries/$inquiryId"
      params={{ inquiryId: item.id }}
      className="flex flex-col gap-1 rounded-xl border border-border bg-background p-4 outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
    >
      <span className="flex items-center justify-between gap-2">
        <span className="break-keep text-base font-semibold text-foreground">{item.title}</span>
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium",
            INQUIRY_STATUS_BADGE_INK[item.status],
          )}
        >
          {INQUIRY_STATUS_LABEL[item.status]}
        </span>
      </span>
      <span className="text-sm text-muted-foreground">
        {INQUIRY_CATEGORY_LABEL[item.category]} · {formatDate(item.createdAt)}
      </span>
    </Link>
  );
}

function InquiryListSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-16 w-full animate-pulse rounded-xl bg-muted" />
    </div>
  );
}
