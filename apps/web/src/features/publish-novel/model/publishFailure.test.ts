import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toPublishFailure, toPublishFailureMessage } from "./publishFailure";

function apiError(status: number, detail: Record<string, unknown>) {
  return new ApiErrorObject({ status, detail, message: "error" });
}

describe("toPublishFailure", () => {
  it("심사 상한 429 는 시간당과 하루 거절을 window 로 가른다", () => {
    expect(
      toPublishFailure(apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 600, window: "novel_screen_hourly" })),
    ).toEqual({ kind: "hourlyLimit", retryAfterSeconds: 600 });
    expect(
      toPublishFailure(apiError(429, { code: "USER_LIMIT", retryAfterSeconds: 9000, window: "novel_screen_daily_reject" })),
    ).toEqual({ kind: "dailyLimit" });
  });

  it("심사 거절·장애·낡은 화면을 가른다", () => {
    expect(toPublishFailure(apiError(400, { code: "NOVEL_SCREENING_REJECTED" }))).toEqual({ kind: "rejected" });
    expect(toPublishFailure(apiError(503, { code: "NOVEL_SCREENING_UNAVAILABLE" }))).toEqual({ kind: "unavailable" });
    expect(toPublishFailure(apiError(409, { code: "NOVEL_PUBLISH_CONFLICT" }))).toEqual({ kind: "stale" });
    expect(toPublishFailure(new Error("network"))).toEqual({ kind: "failed" });
  });

  it("시간당 상한은 남은 분을 올림해 말한다", () => {
    expect(toPublishFailureMessage({ kind: "hourlyLimit", retryAfterSeconds: 61 })).toContain("2분 뒤");
  });
});
