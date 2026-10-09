import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { NovelReportActionPanel } from "@/features/act-on-novel-report";
import { NOVEL_MODERATION_STATUS_LABELS } from "@/entities/admin-novel";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS, useNovelReportDetailQuery } from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { QueryState } from "@/shared/ui/QueryState";

const SECTION_CLASS = "flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 wrap-anywhere @xl:p-6";
const LINK_CLASS = "admin-hit-area font-medium text-primary hover:underline focus-visible:underline";

export function NovelReportDetailBody({ reportId }: { reportId: string }) {
  const query = useNovelReportDetailQuery(reportId);
  useDocumentTitle("신고 상세", query.data?.evidenceTitle ?? undefined);

  // 이미 처리된 신고도 다시 처리할 수 있어 조치가 늘 있다.
  return (
    <QueryState query={query} skeleton="detail" errorMessage="노벨 신고를 불러오지 못했어요.">
      {(report) => (
        <DetailLayout
          actions={{
            title: "신고 처리",
            triggerLabel: "처리하기",
            summary: `신고 ${REPORT_STATUS_LABELS[report.status]}`,
            render: (host) => <NovelReportActionPanel report={report} onSuccess={host.onDone} />,
          }}
        >
          <section className={SECTION_CLASS}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">
                {REPORT_STATUS_LABELS[report.status]}
              </span>
              <span className="text-sm text-muted-foreground">{formatDateTime(report.createdAt)} 접수</span>
            </div>
            <dl className="grid grid-cols-1 gap-3 text-sm @xl:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">신고 사유</dt>
                <dd>{REPORT_REASON_LABELS[report.reasonCategory]}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">신고 범위</dt>
                <dd>{report.chapterOrdinal === null ? "소설 전체(제목·소개)" : `${report.chapterOrdinal}화`}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">대상 노벨</dt>
                <dd>
                  {report.novelId === null ? (
                    <span className="text-muted-foreground">게시자가 지운 노벨이에요</span>
                  ) : (
                    <Link to="/novels/$novelId" params={{ novelId: report.novelId }} className={LINK_CLASS}>
                      노벨 상세 보기
                      {report.novelModerationStatus !== null &&
                        ` · ${NOVEL_MODERATION_STATUS_LABELS[report.novelModerationStatus]}`}
                    </Link>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">게시자</dt>
                <dd>
                  <Link to="/users/$userId" params={{ userId: report.publisherUserId }} className={LINK_CLASS}>
                    유저 상세 보기
                  </Link>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">신고자</dt>
                <dd>
                  <Link to="/users/$userId" params={{ userId: report.reporterUserId }} className={LINK_CLASS}>
                    유저 상세 보기
                  </Link>
                </dd>
              </div>
              {!!report.resolvedAt && (
                <div>
                  <dt className="text-muted-foreground">처리일시</dt>
                  <dd>{formatDateTime(report.resolvedAt)}</dd>
                </div>
              )}
            </dl>
          </section>

          <section className={SECTION_CLASS}>
            <h2 className="text-lg font-semibold">신고 당시 공개본 사본</h2>
            {report.evidence.available ? (
              <>
                {/* 만료 예정일은 사본이 있을 때만 보인다 — 먼저 파기된 사본에 미래 날짜가 함께 뜨면 아래 안내와 어긋난다. */}
                <p className="break-keep text-xs text-muted-foreground">
                  신고 접수 때 복사해 둔 공개본이에요. 이후 다시 공개·삭제와 별도로 보관하며{" "}
                  {formatDateTime(report.evidence.expiresAt)}에 만료돼요.
                </p>
                <EvidenceBlock title="소설 제목">{report.evidence.title}</EvidenceBlock>
                <EvidenceBlock title="소개">{report.evidence.synopsis}</EvidenceBlock>
                {report.chapterOrdinal !== null && (
                  <>
                    <EvidenceBlock title={`${report.chapterOrdinal}화 제목`}>{report.evidence.chapterTitle}</EvidenceBlock>
                    <EvidenceBlock title={`${report.chapterOrdinal}화 본문`}>{report.evidence.body}</EvidenceBlock>
                  </>
                )}
              </>
            ) : (
              <p role="status" className="text-sm text-muted-foreground">
                보관기간이 끝났거나 파기된 사본은 제공하지 않아요.
              </p>
            )}
          </section>
        </DetailLayout>
      )}
    </QueryState>
  );
}

/** 사본 칸은 처리자가 대조하는 본문이라 같은 웰로 묶는다. card 위 채움은 `secondary` 다(`bg-muted` 는 card 와 값이 같아
 * 사라진다). 빈 칸 안내는 웰 밖에 둔다 — `secondary` 위 `muted-foreground` 는 라이트에서 AA 미달이다. */
function EvidenceBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-sm font-medium">{title}</h3>
      {children ? (
        <p className="max-w-prose whitespace-pre-wrap break-keep rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
          {children}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">비어 있음</p>
      )}
    </div>
  );
}
