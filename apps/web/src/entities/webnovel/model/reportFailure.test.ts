import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toWebnovelReportErrorMessage } from "./reportFailure";

function apiError(status: number, detail: Record<string, unknown>) {
  return new ApiErrorObject({ status, detail, message: "error" });
}

describe("toWebnovelReportErrorMessage", () => {
  it("내 노벨 신고와 한도 초과를 가른다", () => {
    expect(toWebnovelReportErrorMessage(apiError(403, { code: "NOVEL_REPORT_OWN" }))).toBe("내가 공개한 소설은 신고할 수 없어요.");
    expect(toWebnovelReportErrorMessage(apiError(429, { code: "NOVEL_REPORT_RATE_LIMITED", retryAfterSeconds: 10 }))).toContain(
      "잠시 후",
    );
  });

  it("사라진 대상은 신고할 수 없다고 말한다", () => {
    expect(toWebnovelReportErrorMessage(apiError(404, { code: "NOVEL_COMMENT_NOT_FOUND" }))).toBe("지금은 신고할 수 없는 글이에요.");
  });
});
