// `en-CA`는 날짜를 `YYYY-MM-DD`로 적는 로캘이라, 서버가 받는 KST 날짜 문자열과 `<input type="date">`의 값 형식을
// 한 번에 만든다. 브라우저 시간대와 무관하게 서울 기준 날짜다.
const KST_DATE_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** 그 순간의 서울 날짜(`YYYY-MM-DD`). 값이 없으면 지금. 같은 형식이라 문자열 비교가 날짜 비교다. */
export function toKstDateString(value: string | Date = new Date()) {
  return KST_DATE_FORMATTER.format(typeof value === "string" ? new Date(value) : value);
}
