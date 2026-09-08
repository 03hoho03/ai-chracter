import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

import { formatCount } from "@/shared/lib/format/formatCount";

import { useCountsQuery } from "../api/useCountsQuery";

const CARD_CLASS = "flex flex-1 flex-col gap-2 rounded-xl border border-border bg-card p-6";
const NUMBER_CLASS = "text-xl font-bold tabular-nums text-foreground";
const GRID_CLASS = "grid grid-cols-2 gap-4 sm:grid-cols-4";

/** 숫자 4개(총 유저 / 총 작품 / 오늘 메시지 / 처리 대기 신고). 이 영역만 실패해도 나머지
 * 세 영역(TrendChart/PopularList/ActivityFeed)은 각자 독립적으로 로딩·렌더된다. */
export function CountCards() {
  const countsQuery = useCountsQuery();

  if (countsQuery.isPending) {
    return (
      <div className={GRID_CLASS}>
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="h-24 animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    );
  }

  if (countsQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        핵심 지표를 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  return (
    <div className={GRID_CLASS}>
      <div className={CARD_CLASS}>
        <span className="text-sm text-muted-foreground">총 유저</span>
        <span className={NUMBER_CLASS}>{formatCount(countsQuery.data.totalUsers)}</span>
      </div>
      <div className={CARD_CLASS}>
        <span className="text-sm text-muted-foreground">총 작품</span>
        <span className={NUMBER_CLASS}>{formatCount(countsQuery.data.totalContents)}</span>
      </div>
      <div className={CARD_CLASS}>
        <span className="text-sm text-muted-foreground">오늘 메시지</span>
        <span className={NUMBER_CLASS}>{formatCount(countsQuery.data.todayMessages)}</span>
      </div>
      {/* 처리 대기 신고 카드는 신고 목록으로 가는 진입점이다(goal-prompt 4장 1단계). */}
      <Link
        to="/reports"
        className={cn(
          CARD_CLASS,
          "outline-none motion-safe:transition-colors hover:bg-accent/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        )}
      >
        <span className="text-sm text-muted-foreground">처리 대기 신고</span>
        <span className={NUMBER_CLASS}>{formatCount(countsQuery.data.pendingReports)}</span>
      </Link>
    </div>
  );
}
