import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { CHAT_REPORT_RATE_LIMITED, reportErrorMessage } from "./reportErrorMessage";

const GENERIC = "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.";

describe("reportErrorMessage", () => {
  it("tells the wait time for the report rate limit", () => {
    const error = new ApiErrorObject({
      status: 429,
      message: "Too Many Requests",
      detail: { code: CHAT_REPORT_RATE_LIMITED, message: "잠시 후 다시 신고해 주세요.", retryAfterSeconds: 42, windowSeconds: 60 },
    });
    expect(reportErrorMessage(error)).toBe("42초 후 다시 신고할 수 있어요. 고른 사유는 그대로 남아 있어요.");
  });

  it("falls back to a wait message when the rate limit carries no wait time", () => {
    const error = new ApiErrorObject({ status: 429, message: "", detail: { code: CHAT_REPORT_RATE_LIMITED } });
    expect(reportErrorMessage(error)).toBe("신고를 너무 빠르게 보냈어요. 잠시 후 다시 시도해주세요.");
  });

  // 분기 기준은 status 가 아니라 code 다 — 다른 모양의 429 를 신고 제한 안내로 오인하지 않는다.
  it("does not treat a 429 without the report code as the report rate limit", () => {
    const error = new ApiErrorObject({ status: 429, message: "", detail: { code: "USER_LIMIT", retryAfterSeconds: 5 } });
    expect(reportErrorMessage(error)).toBe(GENERIC);
  });

  it("explains a response that no longer exists", () => {
    const error = new ApiErrorObject({ status: 404, message: "Message not found", detail: "Message not found" });
    expect(reportErrorMessage(error)).toBe("이 응답을 찾을 수 없어요. 다시 생성됐거나 삭제됐을 수 있어요.");
  });

  it("uses the generic message for other failures and never shows the server detail", () => {
    expect(reportErrorMessage(new ApiErrorObject({ status: 500, message: "boom", detail: "boom" }))).toBe(GENERIC);
    expect(reportErrorMessage(new Error("network"))).toBe(GENERIC);
  });
});
