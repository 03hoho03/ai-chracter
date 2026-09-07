const RELATIVE_TIME_FORMATTER = new Intl.RelativeTimeFormat("ko", { numeric: "always" });

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const MONTH_MS = 30 * DAY_MS;
const YEAR_MS = 12 * MONTH_MS;

/** 채팅 목록의 상대 시각 표기(`3분 전`/`2시간 전`/`5일 전`). `now`를 인자로 받는 순수 함수라 테스트가
 * 시스템 시간에 의존하지 않는다. 60초 미만과 미래 시각(서버·클라이언트 시계 오차로 iso가 now보다
 * 뒤일 때)은 둘 다 "방금"으로 흡수한다 — 안 그러면 "1분 후"가 찍혀 버그처럼 보인다. */
export function formatRelativeTime(iso: string, now: Date): string {
  const diffMs = now.getTime() - new Date(iso).getTime();
  if (diffMs < MINUTE_MS) return "방금";

  if (diffMs < HOUR_MS) return RELATIVE_TIME_FORMATTER.format(-Math.floor(diffMs / MINUTE_MS), "minute");
  if (diffMs < DAY_MS) return RELATIVE_TIME_FORMATTER.format(-Math.floor(diffMs / HOUR_MS), "hour");
  if (diffMs < MONTH_MS) return RELATIVE_TIME_FORMATTER.format(-Math.floor(diffMs / DAY_MS), "day");
  if (diffMs < YEAR_MS) return RELATIVE_TIME_FORMATTER.format(-Math.floor(diffMs / MONTH_MS), "month");
  return RELATIVE_TIME_FORMATTER.format(-Math.floor(diffMs / YEAR_MS), "year");
}
