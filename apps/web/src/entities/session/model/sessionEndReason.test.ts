import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { getSessionEndReason } from "./sessionEndReason";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getSessionEndReason", () => {
  it("세션 소실 401이면 로그인이 풀린 것이다", () => {
    expect(getSessionEndReason(apiError(401, "Not authenticated"))).toBe("sessionLost");
  });

  it("정지 403이면 정지다 — 다시 로그인해도 안 풀리므로 세션 소실과 가른다", () => {
    expect(getSessionEndReason(apiError(403, "Account suspended"))).toBe("suspended");
  });

  it("같은 상태 코드의 다른 거절(재동의 403·본인인증 403·로그인 실패 401)은 해당 없다", () => {
    expect(getSessionEndReason(apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" }))).toBeUndefined();
    expect(getSessionEndReason(apiError(403, { code: "IDENTITY_VERIFICATION_REQUIRED" }))).toBeUndefined();
    expect(getSessionEndReason(apiError(401, "Invalid email or password"))).toBeUndefined();
  });

  it("세션과 무관한 실패는 해당 없다", () => {
    expect(getSessionEndReason(apiError(429, { window: "day" }))).toBeUndefined();
    expect(getSessionEndReason(apiError(500))).toBeUndefined();
    expect(getSessionEndReason(new Error("network"))).toBeUndefined();
  });
});
