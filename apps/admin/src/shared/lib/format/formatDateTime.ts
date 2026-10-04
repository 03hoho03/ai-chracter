const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const DATE_FORMATTER = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
const TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit" });

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

/** `formatDateTime` 과 같은 표기를 날짜·시각 두 덩이로 나눈다 — 좁은 표 칸에서 덩이 사이에서만 줄을 바꾸려는 자리용. */
export function formatDateTimeParts(value: string) {
  const date = new Date(value);
  return { date: DATE_FORMATTER.format(date), time: TIME_FORMATTER.format(date) };
}

/** 대시보드 최근 활동처럼 최근 며칠만 보는 자리 — 연도를 뺀다. */
export function formatMonthDayTime(value: string) {
  return MONTH_DAY_TIME_FORMATTER.format(new Date(value));
}
