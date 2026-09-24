import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { isSessionLostError } from "./sessionLost";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("isSessionLostError", () => {
  it("401 + 'Not authenticated'면 true다", () => {
    expect(isSessionLostError(apiError(401, "Not authenticated"))).toBe(true);
  });

  it("401이어도 로그인 실패('Invalid email or password')는 세션 소실이 아니다", () => {
    expect(isSessionLostError(apiError(401, "Invalid email or password"))).toBe(false);
  });

  it.each([400, 403, 500])("같은 detail이어도 401이 아니면(%d) false다", (status) => {
    expect(isSessionLostError(apiError(status, "Not authenticated"))).toBe(false);
  });

  it("ApiError가 아닌 예외는 false다", () => {
    expect(isSessionLostError(new Error("Not authenticated"))).toBe(false);
  });
});
