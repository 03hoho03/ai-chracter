import { describe, expect, it } from "vitest";

import { formatSnapshotTime } from "./snapshotTime";

describe("formatSnapshotTime", () => {
  it("writes month, day and time so versions saved the same day stay apart", () => {
    const local = new Date(2026, 9, 8, 23, 2);
    expect(formatSnapshotTime(local.toISOString())).toBe("10월 8일 오후 11:02");
  });
});
