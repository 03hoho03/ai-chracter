import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { FileQuestion } from "lucide-react";

import {
  INQUIRY_CATEGORY_LABEL,
  INQUIRY_STATUS_BADGE_INK,
  INQUIRY_STATUS_LABEL,
  type MyInquiryDetailResponse,
  useMyInquiryDetailQuery,
} from "@/entities/inquiry";
import { formatDate } from "@/shared/lib/time/formatDate";

/** `/inquiries/$inquiryId` — 내가 쓴 문의 + 답변. `requireSession`으로 로그인 사용자만 접근하고,
 * 남의 문의는 서버가 404를 준다(403이 아니라 — 존재 여부를 흘리지 않는다, techspec.md §4-4). */
export function InquiryDetailPage({ inquiryId }: { inquiryId: string }) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <InquiryDetailBody inquiryId={inquiryId} />
    </main>
  );
}

function InquiryDetailBody({ inquiryId }: { inquiryId: string }) {
  const inquiryDetailQuery = useMyInquiryDetailQuery(inquiryId);

  if (inquiryDetailQuery.isPending) {
    return <InquiryDetailSkeleton />;
  }

  if (inquiryDetailQuery.isError) {
    if (inquiryDetailQuery.error.status === 404) {
      return (
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
          <p className="text-lg font-semibold text-foreground">찾을 수 없는 문의예요</p>
          <p className="text-sm break-keep text-muted-foreground">
            삭제되었거나 잘못된 주소예요.{" "}
            <Link
              to="/inquiries"
              className="font-medium text-primary hover:underline focus-visible:underline"
            >
              내 문의 내역
            </Link>
            으로 돌아가세요.
          </p>
        </div>
      );
    }

    return (
      <p className="text-sm text-destructive-text">문의를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
    );
  }

  return <InquiryDetailContent inquiry={inquiryDetailQuery.data} />;
}

function InquiryDetailContent({ inquiry }: { inquiry: MyInquiryDetailResponse }) {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <h1 className="break-keep text-2xl font-bold tracking-tight text-foreground">{inquiry.title}</h1>
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium",
              INQUIRY_STATUS_BADGE_INK[inquiry.status],
            )}
          >
            {INQUIRY_STATUS_LABEL[inquiry.status]}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          {INQUIRY_CATEGORY_LABEL[inquiry.category]} · {formatDate(inquiry.createdAt)}
        </p>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">문의 내용</h2>
        <p className="whitespace-pre-wrap break-keep text-sm text-foreground">{inquiry.body}</p>
        {inquiry.attachmentUrl && (
          <a href={inquiry.attachmentUrl} target="_blank" rel="noreferrer" className="w-fit">
            <img
              src={inquiry.attachmentUrl}
              alt="첨부한 스크린샷"
              loading="lazy"
              decoding="async"
              className="max-h-64 rounded-lg border border-border object-contain"
            />
          </a>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">답변</h2>
        {inquiry.replyBody ? (
          <>
            <p className="whitespace-pre-wrap break-keep text-sm text-foreground">{inquiry.replyBody}</p>
            {inquiry.answeredAt && (
              <p className="text-xs text-muted-foreground">{formatDate(inquiry.answeredAt)} 답변</p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">아직 답변이 등록되지 않았어요.</p>
        )}
      </section>
    </>
  );
}

function InquiryDetailSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-7 w-2/3 animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-full animate-pulse rounded bg-muted" />
      <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
    </div>
  );
}
