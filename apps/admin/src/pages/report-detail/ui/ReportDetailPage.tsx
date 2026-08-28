import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import { ReportActionPanel } from "../../../features/act-on-report";
import {
  CONTENT_TYPE_LABELS,
  MODERATION_STATUS_LABELS,
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useReportDetailQuery,
} from "../../../entities/report";

const dateTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

interface ReportDetailPageProps {
  reportId: string;
}

export function ReportDetailPage({ reportId }: ReportDetailPageProps) {
  const reportDetailQuery = useReportDetailQuery(reportId);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-10">
      <Button asChild variant="outline" size="sm" className="self-start">
        <Link to="/reports">목록으로</Link>
      </Button>

      <h1 className="text-2xl font-bold tracking-tight text-foreground">신고 상세</h1>

      {reportDetailQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {reportDetailQuery.isError && (
        <p className="text-sm text-destructive-text">신고 정보를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {reportDetailQuery.data && (
        <>
          <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                {REPORT_STATUS_LABELS[reportDetailQuery.data.status]}
              </span>
              <span className="text-sm text-muted-foreground">
                {dateTimeFormatter.format(new Date(reportDetailQuery.data.createdAt))} 접수
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div>
                <dt className="text-muted-foreground">신고 사유</dt>
                <dd className="text-foreground">{REPORT_REASON_LABELS[reportDetailQuery.data.reasonCategory]}</dd>
              </div>
              {reportDetailQuery.data.resolvedAt && (
                <div>
                  <dt className="text-muted-foreground">처리일시</dt>
                  <dd className="text-foreground">
                    {dateTimeFormatter.format(new Date(reportDetailQuery.data.resolvedAt))}
                  </dd>
                </div>
              )}
            </dl>
          </section>

          <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
            <h2 className="text-lg font-semibold text-foreground">대상 콘텐츠</h2>

            <div className="flex gap-4">
              <div className="flex size-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted">
                {reportDetailQuery.data.content.thumbnailUrl && (
                  <img
                    src={reportDetailQuery.data.content.thumbnailUrl}
                    alt=""
                    className="size-full object-cover"
                  />
                )}
              </div>
              <div className="flex min-w-0 flex-col justify-center gap-1">
                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <span>{CONTENT_TYPE_LABELS[reportDetailQuery.data.content.type]}</span>
                  <span aria-hidden>·</span>
                  <span>{MODERATION_STATUS_LABELS[reportDetailQuery.data.content.moderationStatus]}</span>
                </div>
                <p className="truncate text-base font-semibold text-foreground">
                  {reportDetailQuery.data.content.name || "(이름 없음)"}
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-medium text-foreground">설명</h3>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                {reportDetailQuery.data.content.detailDescription || "-"}
              </p>
            </div>

            {reportDetailQuery.data.content.prompt && (
              <div className="flex flex-col gap-1">
                <h3 className="text-sm font-medium text-foreground">프롬프트</h3>
                <p className="whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                  {reportDetailQuery.data.content.prompt}
                </p>
              </div>
            )}
          </section>

          <ReportActionPanel
            reportId={reportDetailQuery.data.id}
            reportPending={reportDetailQuery.data.status === "pending"}
            contentName={reportDetailQuery.data.content.name || "(이름 없음)"}
            contentRestricted={reportDetailQuery.data.content.moderationStatus === "restricted"}
          />
        </>
      )}
    </main>
  );
}
