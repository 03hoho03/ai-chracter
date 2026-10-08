import { describe, expect, it } from "vitest";

import { formatSnapshotTime } from "./snapshotTime";

function localIso(hours: number, minutes: number): string {
  return new Date(2026, 9, 8, hours, minutes).toISOString();
}

describe("formatSnapshotTime", () => {
  it("writes month, day and time so versions saved the same day stay apart", () => {
    expect(formatSnapshotTime(localIso(23, 2))).toBe("10월 8일 오후 11:02");
  });

  it("writes midnight as 오전 12 and noon as 오후 12", () => {
    expect(formatSnapshotTime(localIso(0, 5))).toBe("10월 8일 오전 12:05");
    expect(formatSnapshotTime(localIso(12, 0))).toBe("10월 8일 오후 12:00");
  });

  it("does not pad the morning hour", () => {
    expect(formatSnapshotTime(localIso(9, 7))).toBe("10월 8일 오전 9:07");
  });
});
