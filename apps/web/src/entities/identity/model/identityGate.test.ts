import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { isIdentityGated, isIdentityVerificationRequiredError } from "./identityGate";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("isIdentityVerificationRequiredError", () => {
  it("403 IDENTITY_VERIFICATION_REQUIRED 만 참이다", () => {
    expect(isIdentityVerificationRequiredError(apiError(403, { code: "IDENTITY_VERIFICATION_REQUIRED" }))).toBe(true);
  });

  // 같은 403 을 쓰는 다른 거절에 본인인증 안내를 띄우면 이용자가 엉뚱한 일을 하러 간다.
  it.each([
    ["재동의 403", apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" })],
    ["결제 나이 제한 403", apiError(403, { code: "PAYMENT_AGE_RESTRICTED" })],
    ["문자열 detail 의 정지 403", apiError(403, "Account suspended")],
    ["같은 코드여도 403 이 아님", apiError(429, { code: "IDENTITY_VERIFICATION_REQUIRED" })],
    ["detail 없음", apiError(403, undefined)],
    ["ApiError 가 아님", new Error("x")],
  ])("%s 는 거짓이다", (_, error) => {
    expect(isIdentityVerificationRequiredError(error)).toBe(false);
  });
});

describe("isIdentityGated", () => {
  it.each([
    [true, false, true],
    [true, true, false],
    [false, false, false],
    [false, true, false],
  ])("게이트 %s · 인증 %s → %s", (identityGateEnabled, identityVerified, expected) => {
    expect(isIdentityGated({ identityGateEnabled, identityVerified })).toBe(expected);
  });
});
