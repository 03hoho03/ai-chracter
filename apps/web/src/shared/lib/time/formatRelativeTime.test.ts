import { describe, expect, it } from "vitest";

import { formatRelativeTime } from "./formatRelativeTime";

const NOW = new Date("2026-09-07T12:00:00.000Z");

function isoBefore(ms: number): string {
  return new Date(NOW.getTime() - ms).toISOString();
}

describe("formatRelativeTime", () => {
  it("returns 방금 under 60 seconds", () => {
    expect(formatRelativeTime(isoBefore(59_000), NOW)).toBe("방금");
  });

  it("returns 1분 전 at the 60 second boundary", () => {
    expect(formatRelativeTime(isoBefore(60_000), NOW)).toBe("1분 전");
  });

  it("returns minutes under 60 minutes", () => {
    expect(formatRelativeTime(isoBefore(3 * 60_000), NOW)).toBe("3분 전");
  });

  it("returns 1시간 전 at the 60 minute boundary", () => {
    expect(formatRelativeTime(isoBefore(60 * 60_000), NOW)).toBe("1시간 전");
  });

  it("returns hours under 24 hours", () => {
    expect(formatRelativeTime(isoBefore(2 * 60 * 60_000), NOW)).toBe("2시간 전");
  });

  it("returns 1일 전 at the 24 hour boundary", () => {
    expect(formatRelativeTime(isoBefore(24 * 60 * 60_000), NOW)).toBe("1일 전");
  });

  it("returns days under 30 days", () => {
    expect(formatRelativeTime(isoBefore(5 * 24 * 60 * 60_000), NOW)).toBe("5일 전");
  });

  it("returns 1개월 전 at the 30 day boundary", () => {
    expect(formatRelativeTime(isoBefore(30 * 24 * 60 * 60_000), NOW)).toBe("1개월 전");
  });

  it("returns months under 12 months", () => {
    expect(formatRelativeTime(isoBefore(2 * 30 * 24 * 60 * 60_000), NOW)).toBe("2개월 전");
  });

  it("returns 1년 전 at the 12 month boundary", () => {
    expect(formatRelativeTime(isoBefore(12 * 30 * 24 * 60 * 60_000), NOW)).toBe("1년 전");
  });

  it("returns years beyond the 12 month boundary", () => {
    expect(formatRelativeTime(isoBefore(2 * 12 * 30 * 24 * 60 * 60_000), NOW)).toBe("2년 전");
  });

  it("absorbs future timestamps (clock skew) into 방금", () => {
    const future = new Date(NOW.getTime() + 5_000).toISOString();
    expect(formatRelativeTime(future, NOW)).toBe("방금");
  });
});
