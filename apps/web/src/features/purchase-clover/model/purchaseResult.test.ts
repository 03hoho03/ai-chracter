import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toCreatePaymentFailure } from "./purchaseResult";

function apiError(status: number, code: string) {
  return new ApiErrorObject({ status, message: "x", detail: { code } });
}

describe("toCreatePaymentFailure", () => {
  it.each([
    ["19세 미만", apiError(403, "PAYMENT_AGE_RESTRICTED"), "ageRestricted"],
    ["본인인증 전", apiError(403, "IDENTITY_VERIFICATION_REQUIRED"), "identityRequired"],
    // 일반 오류로 접으면 다이얼로그의 "문의" 문장이 전역 재동의 모달과 겹친다.
    ["재동의 전", apiError(403, "LEGAL_RECONSENT_REQUIRED"), "reconsentRequired"],
    ["결제 꺼짐", apiError(503, "PAYMENTS_UNAVAILABLE"), "unavailable"],
    ["그 밖", apiError(500, "SOMETHING"), "failed"],
    ["네트워크", new Error("x"), "failed"],
  ])("%s", (_, error, expected) => {
    expect(toCreatePaymentFailure(error)).toBe(expected);
  });
});
