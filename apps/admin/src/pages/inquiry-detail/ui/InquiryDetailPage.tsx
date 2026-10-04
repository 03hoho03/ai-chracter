import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { InquiryReplyPanel } from "@/features/reply-inquiry";
import { INQUIRY_CATEGORY_LABELS, INQUIRY_STATUS_LABELS, useInquiryDetailQuery } from "@/entities/inquiry";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

type InquiryDetailPageProps = {
  inquiryId: string;
}

export function InquiryDetailPage({ inquiryId }: InquiryDetailPageProps) {
  // 마지막으로 본 목록(필터·검색어·페이지)으로 돌아간다 — 대시보드 등 다른 입구로 들어왔어도 같다.
  const rememberedListSearch = useRememberedListSearch("/inquiries/");
  return (
    <PageContainer>
      <PageHeader
        title="문의 상세"
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/inquiries" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      <InquiryDetailBody inquiryId={inquiryId} />
    </PageContainer>
  );
}

type InquiryDetailBodyProps = {
  inquiryId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportDetailPage` 관용구).
 * 답변 폼은 이 화면의 본문 그 자체라 조치 열·하단 바로 빼지 않고 문의 아래에 둔다. 문의 제목·본문·작성자는 유저가
 * 쓴 글이라 띄어쓰기 없이 길 수 있어 아무 데서나 꺾는다. */
function InquiryDetailBody({ inquiryId }: InquiryDetailBodyProps) {
  const inquiryDetailQuery = useInquiryDetailQuery(inquiryId);
  useDocumentTitle("문의 상세", inquiryDetailQuery.data?.title);

  return (
    <QueryState query={inquiryDetailQuery} errorMessage="문의 정보를 불러오지 못했어요.">
      {(inquiry) => (
        <DetailLayout actions={null}>
          <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                {INQUIRY_STATUS_LABELS[inquiry.status]}
              </span>
              <span className="text-sm text-muted-foreground">{formatDateTime(inquiry.createdAt)} 접수</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div className="min-w-0">
                <dt className="text-muted-foreground">작성자</dt>
                <dd className="break-keep text-foreground wrap-anywhere">
                  {inquiry.authorNickname} · {inquiry.authorEmail}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">카테고리</dt>
                <dd className="text-foreground">{INQUIRY_CATEGORY_LABELS[inquiry.category]}</dd>
              </div>
            </dl>
          </section>

          <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6">
            <h2 className="break-keep text-lg font-semibold text-foreground wrap-anywhere">{inquiry.title}</h2>

            {/* 문의 본문은 유저가 쓴 일반 텍스트다 — `Markdown`을 쓰지 않는다. */}
            <p className="whitespace-pre-wrap break-keep text-sm text-foreground wrap-anywhere">{inquiry.body}</p>

            {!!inquiry.attachmentUrl && (
              <div className="flex h-64 w-full max-w-md items-center justify-center overflow-hidden rounded-lg border border-border bg-secondary">
                <img
                  src={inquiry.attachmentUrl}
                  alt=""
                  className="size-full object-cover"
                  // 신고 상세의 작품 썸네일에는 없는 핸들러다: 그 썸네일은 정적 자산이라 만료가 없지만, 문의 첨부는
                  // presigned GET URL이라 `settings.s3_presigned_url_expires_seconds` 후 깨진다. 상세를
                  // 열어둔 채 오래 두는 경우를 대비해 실패 시 상세 쿼리를 refetch해 새 URL을 받는다.
                  onError={() => void inquiryDetailQuery.refetch()}
                />
              </div>
            )}
          </section>

          <InquiryReplyPanel key={inquiry.id} inquiryId={inquiry.id} initialReplyBody={inquiry.replyBody} />
        </DetailLayout>
      )}
    </QueryState>
  );
}
