const KST_DATE_FORMAT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** 한국 시각 기준 `YYYY.MM.DD`. 약관 시행일처럼 "한국 시각 그날"로 정해진 날짜를 찍는 자리에 쓴다.
 *
 * `formatDate`는 브라우저 시간대를 따르므로 한국 밖의 브라우저에서는 KST 00:00 시행이 하루 앞 날짜로 보인다.
 * 시행일은 약관 문언("시행일")과 같은 날짜로 보여야 해서 시간대를 고정한다. */
export function formatKstDate(iso: string): string {
  const parts = KST_DATE_FORMAT.formatToParts(new Date(iso));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year")}.${part("month")}.${part("day")}`;
}
