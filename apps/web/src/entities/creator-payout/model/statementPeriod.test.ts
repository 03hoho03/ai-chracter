import { describe, expect, it } from "vitest";

import { formatStatementPeriod } from "./statementPeriod";

const WINDOW = { windowStart: "2026-08-07T03:00:00Z", windowEnd: "2026-11-05T03:00:00Z" };

describe("formatStatementPeriod", () => {
  it("월 확정은 그 달 이름이다", () => {
    expect(formatStatementPeriod({ kind: "monthly", periodMonth: "2026-11-01", ...WINDOW })).toEqual({
      title: "2026년 11월",
      range: null,
    });
  });

  // 날짜 문자열을 Date 로 읽으면 UTC 서쪽 시간대에서 전달이 된다 — 달은 글자 그대로 읽는다.
  it("1월은 앞자리 0 없이 그 달이다", () => {
    expect(formatStatementPeriod({ kind: "monthly", periodMonth: "2027-01-01", ...WINDOW }).title).toBe("2027년 1월");
  });

  it("소급은 센 기간을 함께 보인다", () => {
    const period = formatStatementPeriod({ kind: "retro", periodMonth: null, ...WINDOW });
    expect(period.title).toBe("승인 때 소급 정산");
    expect(period.range).toMatch(/^2026\.08\.0\d ~ 2026\.11\.0\d$/);
  });
});
