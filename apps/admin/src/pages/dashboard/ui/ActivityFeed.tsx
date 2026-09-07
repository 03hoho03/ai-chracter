import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import { REPORT_REASON_LABELS } from "@/entities/report";
import { formatMonthDayTime } from "@/shared/lib/format/formatDateTime";

import { useActivityQuery } from "../api/useActivityQuery";

/** 최근 가입 유저 / 최근 등록 작품 / 최근 신고 각 5건. 세 항목 모두 상세로 링크한다. */
export function ActivityFeed() {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-medium text-foreground">최근 활동</h2>
      <ActivityFeedBody />
    </div>
  );
}

/** 카드 셸(제목)은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ActivityFeedBody() {
  const activityQuery = useActivityQuery();

  if (activityQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (activityQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        최근 활동을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">최근 가입</h3>
        {activityQuery.data.recentUsers.length === 0 ? (
          <p className="text-sm text-muted-foreground">최근 가입한 유저가 없어요.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {activityQuery.data.recentUsers.map((user) => (
              <li key={user.id}>
                <Link
                  to="/users/$userId"
                  params={{ userId: user.id }}
                  className="-mx-1 flex items-center justify-between gap-2 rounded-md px-1 text-sm outline-none motion-safe:transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="truncate text-foreground">{user.nickname}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatMonthDayTime(user.createdAt)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">최근 등록 작품</h3>
        {activityQuery.data.recentContents.length === 0 ? (
          <p className="text-sm text-muted-foreground">최근 등록된 작품이 없어요.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {activityQuery.data.recentContents.map((content) => (
              <li key={content.id}>
                <Link
                  to="/contents/$contentId"
                  params={{ contentId: content.id }}
                  className="-mx-1 flex items-center justify-between gap-2 rounded-md px-1 text-sm outline-none motion-safe:transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="truncate text-foreground">
                    <span className="text-muted-foreground">{CONTENT_TYPE_LABELS[content.type]}</span>{" "}
                    {content.name || "(이름 없음)"}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatMonthDayTime(content.createdAt)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">최근 신고</h3>
        {activityQuery.data.recentReports.length === 0 ? (
          <p className="text-sm text-muted-foreground">접수된 신고가 없어요.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {activityQuery.data.recentReports.map((report) => (
              <li key={report.id}>
                <Link
                  to="/reports/$reportId"
                  params={{ reportId: report.id }}
                  className="-mx-1 flex items-center justify-between gap-2 rounded-md px-1 text-sm outline-none motion-safe:transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="truncate text-foreground">
                    <span className="text-muted-foreground">{REPORT_REASON_LABELS[report.reasonCategory]}</span>{" "}
                    {report.contentName || "(이름 없음)"}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatMonthDayTime(report.createdAt)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
