import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS, REPORT_REASON_LABELS } from "@/entities/report";

import { useActivityQuery } from "../api/useActivityQuery";

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** 최근 가입 유저 / 최근 등록 작품 / 최근 신고 각 5건. 신고 항목만 상세로 링크한다 —
 * 유저·작품 상세 화면은 2·3단계에서 생긴다. */
export function ActivityFeed() {
  const activityQuery = useActivityQuery();

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-medium text-foreground">최근 활동</h2>

      {activityQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {activityQuery.isError && (
        <p className="text-sm text-destructive-text">
          최근 활동을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {activityQuery.data && (
        <div className="flex flex-col gap-5">
          <section className="flex flex-col gap-2">
            <h3 className="text-xs font-medium text-muted-foreground">최근 가입</h3>
            {activityQuery.data.recentUsers.length === 0 ? (
              <p className="text-sm text-muted-foreground">최근 가입한 유저가 없어요.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {activityQuery.data.recentUsers.map((user) => (
                  // 유저 상세 화면은 3단계에서 생긴다 — 그때 이 항목에 링크를 건다.
                  <li key={user.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate text-foreground">{user.nickname}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {CREATED_AT_FORMATTER.format(new Date(user.createdAt))}
                    </span>
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
                  // 작품 상세 화면은 2단계에서 생긴다 — 그때 이 항목에 링크를 건다.
                  <li key={content.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate text-foreground">
                      <span className="text-muted-foreground">{CONTENT_TYPE_LABELS[content.type]}</span>{" "}
                      {content.name || "(이름 없음)"}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {CREATED_AT_FORMATTER.format(new Date(content.createdAt))}
                    </span>
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
                        {CREATED_AT_FORMATTER.format(new Date(report.createdAt))}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
