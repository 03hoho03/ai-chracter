import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import { InquiryReplyPanel } from "@/features/reply-inquiry";
import { INQUIRY_CATEGORY_LABELS, INQUIRY_STATUS_LABELS, useInquiryDetailQuery } from "@/entities/inquiry";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

type InquiryDetailPageProps = {
  inquiryId: string;
}

export function InquiryDetailPage({ inquiryId }: InquiryDetailPageProps) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/inquiries">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">문의 상세</h1>

      <InquiryDetailBody inquiryId={inquiryId} />
    </main>
  );
}

type InquiryDetailBodyProps = {
  inquiryId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportDetailPage` 관용구). */
function InquiryDetailBody({ inquiryId }: InquiryDetailBodyProps) {
  const inquiryDetailQuery = useInquiryDetailQuery(inquiryId);

  if (inquiryDetailQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (inquiryDetailQuery.isError) {
    return <p className="text-sm text-destructive-text">문의 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  const inquiry = inquiryDetailQuery.data;

  return (
    <>
      <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
            {INQUIRY_STATUS_LABELS[inquiry.status]}
          </span>
          <span className="text-sm text-muted-foreground">{formatDateTime(inquiry.createdAt)} 접수</span>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-muted-foreground">작성자</dt>
            <dd className="text-foreground">
              {inquiry.authorNickname} · {inquiry.authorEmail}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">카테고리</dt>
            <dd className="text-foreground">{INQUIRY_CATEGORY_LABELS[inquiry.category]}</dd>
          </div>
        </dl>
      </section>

      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">{inquiry.title}</h2>

        {/* 문의 본문은 유저가 쓴 일반 텍스트다(D-19) — `Markdown`을 쓰지 않는다. */}
        <p className="whitespace-pre-wrap break-keep text-sm text-foreground">{inquiry.body}</p>

        {inquiry.attachmentUrl && (
          <div className="flex h-64 w-full max-w-md items-center justify-center overflow-hidden rounded-lg border border-border bg-muted">
            <img
              src={inquiry.attachmentUrl}
              alt=""
              className="size-full object-cover"
              // `report-detail/ui/ReportDetailPage.tsx:85-94` 선례에는 없는 핸들러다: 그 썸네일은
              // 정적 자산이라 만료가 없지만, 문의 첨부는 presigned GET URL이라
              // `settings.s3_presigned_url_expires_seconds` 후 깨진다(techspec.md §6-3). 상세를
              // 열어둔 채 오래 두는 경우를 대비해 실패 시 상세 쿼리를 refetch해 새 URL을 받는다.
              onError={() => void inquiryDetailQuery.refetch()}
            />
          </div>
        )}
      </section>

      <InquiryReplyPanel key={inquiry.id} inquiryId={inquiry.id} initialReplyBody={inquiry.replyBody} />
    </>
  );
}
