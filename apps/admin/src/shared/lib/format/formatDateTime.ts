const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const MONTH_DAY_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** 어드민 표준 일시 표기. 서버가 주는 nullable 시각(`emailVerifiedAt`, `publishedAt` 등)을 그대로
 * 넘길 수 있게 값이 없으면 "-"를 낸다 — 호출부마다 삼항으로 같은 분기를 적지 않기 위함이다. */
export function formatDateTime(value: string | null | undefined) {
  return value ? DATE_TIME_FORMATTER.format(new Date(value)) : "-";
}

/** 대시보드 최근 활동처럼 최근 며칠만 보는 자리 — 연도를 뺀다. */
export function formatMonthDayTime(value: string) {
  return MONTH_DAY_TIME_FORMATTER.format(new Date(value));
}
