import type { components } from "@ai-character-chat/api-types";

import { formatDate } from "@/shared/lib/time/formatDate";

type CreatorPayoutStatement = components["schemas"]["CreatorPayoutStatementView"];

/** 확정 하나의 이름과 센 기간. 월 확정은 그 달(`periodMonth`, `YYYY-MM-DD` 날짜 문자열)로 부르고, 첫 승인 때의 소급은
 * 달에 묶이지 않아 센 기간을 함께 보인다.
 *
 * 달은 문자열에서 바로 읽는다 — `new Date("2026-11-01")` 은 UTC 자정이라 UTC 보다 서쪽 시간대에서 전날(10월)이 된다. */
export function formatStatementPeriod(statement: Pick<CreatorPayoutStatement, "kind" | "periodMonth" | "windowStart" | "windowEnd">): {
  title: string;
  range: string | null;
} {
  if (statement.kind === "monthly" && statement.periodMonth) {
    const [year, month] = statement.periodMonth.split("-");
    return { title: `${year}년 ${Number(month)}월`, range: null };
  }
  return {
    title: "승인 때 소급 정산",
    range: `${formatDate(statement.windowStart)} ~ ${formatDate(statement.windowEnd)}`,
  };
}
