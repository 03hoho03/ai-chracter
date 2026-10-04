import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { canActOnContentReport, ReportActionPanel } from "@/features/act-on-report";
import { CONTENT_TYPE_LABELS, MODERATION_STATUS_LABELS } from "@/entities/admin-content";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS, useReportDetailQuery, type ReportTarget } from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { ChatMessageReportDetailBody } from "./ChatMessageReportDetailBody";
import { CommentReportDetailBody } from "./CommentReportDetailBody";

type ReportDetailPageProps = {
  reportId: string;
  target: ReportTarget;
}

export function ReportDetailPage({ reportId, target }: ReportDetailPageProps) {
  const rememberedListSearch = useRememberedListSearch("/reports/");
  // 마지막으로 본 신고 목록으로 돌아가되, 그 목록이 다른 대상의 표였으면 이 신고의 대상 표로 간다 — 목록 search 의
  // 대상이 비어 있으면 작품 신고 표다.
  const listSearch =
    rememberedListSearch !== undefined && (rememberedListSearch.target ?? "content") === target
      ? rememberedListSearch
      : { target };

  return (
    <PageContainer>
      <PageHeader
        title="신고 상세"
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/reports" search={listSearch}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      <TargetReportDetailBody target={target} reportId={reportId} />
    </PageContainer>
  );
}

/** 대상마다 상세 API가 다르다. 두 갈래 삼항이면 새 대상이 그 id로 작품 신고 상세를 불러 404 화면이
 * 되므로 대상을 하나씩 명시하고, `assertNever`로 대상이 늘었을 때 여기서 컴파일이 깨지게 한다. */
function TargetReportDetailBody({ target, reportId }: { target: ReportTarget; reportId: string }) {
  switch (target) {
    case "content":
      return <ReportDetailBody reportId={reportId} />;
    case "comment":
      return <CommentReportDetailBody reportId={reportId} />;
    case "chat-message":
      return <ChatMessageReportDetailBody reportId={reportId} />;
    default:
      return assertNever(target);
  }
}

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}

type ReportDetailBodyProps = {
  reportId: string;
};

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ReportDetailBody({ reportId }: ReportDetailBodyProps) {
  const reportDetailQuery = useReportDetailQuery(reportId);
  useDocumentTitle("신고 상세", reportDetailQuery.data?.content.name);

  return (
    <QueryState query={reportDetailQuery} skeleton="detail" errorMessage="신고 정보를 불러오지 못했어요.">
      {(report) => {
        const isReportPending = report.status === "pending";
        const isContentRestricted = report.content.moderationStatus === "restricted";
        const contentName = report.content.name || "(이름 없음)";

        return (
          <DetailLayout
            actions={
              canActOnContentReport({ isReportPending, isContentRestricted })
                ? {
                    title: "신고 처리",
                    triggerLabel: "처리하기",
                    summary: isContentRestricted
                      ? `신고 ${REPORT_STATUS_LABELS[report.status]} · 작품 이용제한 중`
                      : `신고 ${REPORT_STATUS_LABELS[report.status]}`,
                    render: (host) => (
                      <ReportActionPanel
                        reportId={report.id}
                        isReportPending={isReportPending}
                        contentName={contentName}
                        isContentRestricted={isContentRestricted}
                        onSuccess={host.onDone}
                      />
                    ),
                  }
                : null
            }
          >
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                  {REPORT_STATUS_LABELS[report.status]}
                </span>
                <span className="text-sm text-muted-foreground">{formatDateTime(report.createdAt)} 접수</span>
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <div>
                  <dt className="text-muted-foreground">신고 사유</dt>
                  <dd className="text-foreground">{REPORT_REASON_LABELS[report.reasonCategory]}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">신고자</dt>
                  <dd className="text-foreground">
                    <Link
                      to="/users/$userId"
                      params={{ userId: report.reporterUserId }}
                      className="admin-hit-area font-medium text-primary hover:underline"
                    >
                      유저 상세 보기
                    </Link>
                  </dd>
                </div>
                {!!report.resolvedAt && (
                  <div>
                    <dt className="text-muted-foreground">처리일시</dt>
                    <dd className="text-foreground">{formatDateTime(report.resolvedAt)}</dd>
                  </div>
                )}
              </dl>
            </section>

            <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6">
              <h2 className="text-lg font-semibold text-foreground">대상 콘텐츠</h2>

              <div className="flex gap-4">
                <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary">
                  {!!report.content.thumbnailUrl && (
                    <img src={report.content.thumbnailUrl} alt="" className="size-full object-cover" />
                  )}
                </div>
                <div className="flex min-w-0 flex-col justify-center gap-1">
                  <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <span>{CONTENT_TYPE_LABELS[report.content.type]}</span>
                    <span aria-hidden>·</span>
                    <span>{MODERATION_STATUS_LABELS[report.content.moderationStatus]}</span>
                  </div>
                  <p className="break-keep text-lg font-semibold text-foreground wrap-anywhere">{contentName}</p>
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <h3 className="text-sm font-medium text-foreground">설명</h3>
                <p className="whitespace-pre-wrap break-keep text-sm text-muted-foreground wrap-anywhere">
                  {report.content.detailDescription || "-"}
                </p>
              </div>

              {!!report.content.prompt && (
                <div className="flex flex-col gap-1">
                  <h3 className="text-sm font-medium text-foreground">프롬프트</h3>
                  <p className="whitespace-pre-wrap rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
                    {report.content.prompt}
                  </p>
                </div>
              )}
            </section>
          </DetailLayout>
        );
      }}
    </QueryState>
  );
}
