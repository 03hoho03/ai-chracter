import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { MODERATION_STATUS_LABELS } from "@/entities/admin-content";
import {
  NOVEL_MODERATION_STATUS_LABELS,
  NOVEL_VISIBILITY_LABELS,
  useNovelDetailQuery,
  type AdminNovelDetailResponse,
} from "@/entities/admin-novel";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS } from "@/entities/report";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

import { hiddenReasons } from "../lib/hiddenReasons";
import { NovelActions } from "./NovelActions";
import { NovelChaptersSection } from "./NovelChaptersSection";
import { NovelCommentsSection } from "./NovelCommentsSection";
import { NovelScreeningsSection } from "./NovelScreeningsSection";

const SECTION_CLASS = "flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6";

type NovelDetailPageProps = {
  novelId: string;
};

export function NovelDetailPage({ novelId }: NovelDetailPageProps) {
  // 마지막으로 본 목록(필터·페이지)으로 돌아간다 — 신고 상세 등 다른 입구로 들어왔어도 같다.
  const rememberedListSearch = useRememberedListSearch("/novels/");
  return (
    <PageContainer>
      <PageHeader
        title="노벨 상세"
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/novels" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      <NovelDetailBody novelId={novelId} />
    </PageContainer>
  );
}

/** 목록 링크·제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function NovelDetailBody({ novelId }: NovelDetailPageProps) {
  const novelDetailQuery = useNovelDetailQuery(novelId);
  useDocumentTitle("노벨 상세", novelDetailQuery.data?.title);

  return (
    <QueryState query={novelDetailQuery} skeleton="detail" errorMessage="노벨 정보를 불러오지 못했어요.">
      {(novel) => (
        // 조치(홈 노벨·이용제한/해제)는 공개 상태 행이 있는 한 늘 있다 — 거둔 노벨도 이용제한을 걸어 둘 수 있다.
        <DetailLayout
          actions={{
            title: "조치",
            triggerLabel: "조치하기",
            summary: `${NOVEL_VISIBILITY_LABELS[novel.visibility]} · ${NOVEL_MODERATION_STATUS_LABELS[novel.moderationStatus]}`,
            render: (host) => <NovelActions novel={novel} onSuccess={host.onDone} />,
          }}
        >
          <NovelSummary novel={novel} />
          <NovelChaptersSection novelId={novel.id} chapters={novel.chapters} />
          <NovelScreeningsSection screenings={novel.screenings} />
          <NovelReportsSection novel={novel} />
          <NovelCommentsSection novelId={novel.id} />
        </DetailLayout>
      )}
    </QueryState>
  );
}

function NovelSummary({ novel }: { novel: AdminNovelDetailResponse }) {
  const reasons = hiddenReasons(novel);

  return (
    <section className={`${SECTION_CLASS} gap-4`}>
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span>{NOVEL_VISIBILITY_LABELS[novel.visibility]}</span>
          <span aria-hidden>·</span>
          <span>{NOVEL_MODERATION_STATUS_LABELS[novel.moderationStatus]}</span>
          <span aria-hidden>·</span>
          <span className={novel.readable ? undefined : "text-destructive-text"}>
            {novel.readable ? "독자에게 보임" : "독자에게 안 보임"}
          </span>
        </div>
        <p className="break-keep text-lg font-semibold text-foreground wrap-anywhere">{novel.title || "(제목 없음)"}</p>
        <p className="text-xs text-muted-foreground">
          {formatDateTime(novel.firstPublishedAt)} 첫 공개 · {formatDateTime(novel.publishedAt)} 최근 공개
        </p>
      </div>

      {reasons.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border border-destructive/30 bg-destructive/10 p-3">
          <p className="text-sm font-medium text-destructive-text">독자에게 보이지 않는 이유</p>
          <ul className="flex flex-col gap-0.5 text-sm text-foreground">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm @xl:grid-cols-2">
        <div className="min-w-0">
          <dt className="text-muted-foreground">원작</dt>
          <dd className="flex flex-wrap items-baseline gap-x-2">
            <Link
              to="/contents/$contentId"
              params={{ contentId: novel.contentId }}
              className="admin-hit-area break-keep font-medium text-primary wrap-anywhere hover:underline focus-visible:underline"
            >
              {novel.sourceTitle}
            </Link>
            <span className="text-xs text-muted-foreground">
              {novel.sourceModerationStatus === null ? "원작 지워짐" : MODERATION_STATUS_LABELS[novel.sourceModerationStatus]}
            </span>
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-muted-foreground">게시자</dt>
          <dd className="flex flex-wrap items-baseline gap-x-2">
            <Link
              to="/users/$userId"
              params={{ userId: novel.publisherUserId }}
              className="admin-hit-area break-keep font-medium text-primary wrap-anywhere hover:underline focus-visible:underline"
            >
              {novel.publisherNickname ?? "(탈퇴한 게시자)"}
            </Link>
            {novel.publisherSuspended && <span className="text-xs text-destructive-text">이용정지 중</span>}
          </dd>
        </div>
      </dl>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm @xl:grid-cols-4">
        <Stat label="공개 화" value={formatCount(novel.chapterCount)} />
        <Stat label="좋아요" value={formatCount(novel.likeCount)} />
        <Stat label="조회" value={formatCount(novel.viewCount)} />
        <Stat label="대기 신고" value={formatCount(novel.pendingReportCount)} />
        <Stat label="구매(화)" value={formatCount(novel.purchaseCount)} />
        <Stat label="구매자" value={`${formatCount(novel.purchaseBuyerCount)}명`} />
        <Stat label="구매 클로버" value={formatCount(novel.purchaseAmount)} />
      </dl>

      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-foreground">소개(공개본)</h3>
        <p className="max-w-prose whitespace-pre-wrap break-keep text-sm text-muted-foreground wrap-anywhere">
          {novel.synopsis || "-"}
        </p>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

/** 최근 노벨 신고 20개. 처리는 신고 상세에서 한다 — 행이 그리로 간다. */
function NovelReportsSection({ novel }: { novel: AdminNovelDetailResponse }) {
  return (
    <section aria-labelledby="novel-reports-heading" className={SECTION_CLASS}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="novel-reports-heading" className="text-lg font-semibold text-foreground">
          최근 신고
        </h2>
        <Link
          to="/reports"
          search={{ target: "novel" }}
          className="admin-hit-area text-sm font-medium text-primary hover:underline focus-visible:underline"
        >
          노벨 신고 전체 보기
        </Link>
      </div>
      {novel.reports.length === 0 ? (
        <p className="text-sm text-muted-foreground">이 노벨에 들어온 신고가 없어요.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
          {novel.reports.map((report) => (
            <li key={report.id} className="relative flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm hover:bg-secondary">
              <Link
                to="/reports/$reportId"
                params={{ reportId: report.id }}
                search={{ target: "novel" }}
                className="font-medium text-foreground outline-none after:absolute after:inset-0 after:rounded-lg focus-visible:after:outline-1 focus-visible:after:-outline-offset-1 focus-visible:after:outline-ring focus-visible:after:ring-3 focus-visible:after:ring-ring/50"
              >
                {REPORT_REASON_LABELS[report.reasonCategory]}
              </Link>
              <span className="text-muted-foreground">
                {report.chapterOrdinal === null ? "소설 전체" : `${report.chapterOrdinal}화`}
              </span>
              <span className={report.status === "pending" ? "font-medium text-foreground" : "text-muted-foreground"}>
                {REPORT_STATUS_LABELS[report.status]}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(report.createdAt)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
