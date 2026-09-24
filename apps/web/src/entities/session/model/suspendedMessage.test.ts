import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { isSuspendedError } from "./suspendedMessage";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("isSuspendedError", () => {
  it("403 + 'Account suspended'면 true다", () => {
    expect(isSuspendedError(apiError(403, "Account suspended"))).toBe(true);
  });

  it("403이어도 재동의 게이트(detail이 객체)는 정지가 아니다", () => {
    expect(isSuspendedError(apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" }))).toBe(false);
  });

  it.each([400, 401, 409, 500])("같은 detail이어도 403이 아니면(%d) false다", (status) => {
    expect(isSuspendedError(apiError(status, "Account suspended"))).toBe(false);
  });

  it("ApiError가 아닌 예외는 false다", () => {
    expect(isSuspendedError(new Error("Account suspended"))).toBe(false);
  });
});
