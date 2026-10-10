import { describe, expect, it } from "vitest";

import { REQUEST_PAYOUT_MESSAGES, toRequestPayoutFailure } from "./requestPayoutResult";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "" };
}

describe("toRequestPayoutFailure", () => {
  it.each([
    [409, "CREATOR_PAYOUT_INFO_REQUIRED", "infoRequired"],
    [409, "CREATOR_PAYOUT_INFO_UNREADABLE", "infoUnreadable"],
    [409, "CREATOR_PAYOUT_IN_PROGRESS", "inProgress"],
    [422, "CREATOR_PAYOUT_NOTHING_TO_PAY", "nothingToPay"],
    [422, "CREATOR_PAYOUT_BELOW_MINIMUM", "belowMinimum"],
    [403, "CREATOR_PAYOUT_NOT_APPROVED", "notApproved"],
    [403, "CREATOR_PAYOUT_AGE_RESTRICTED", "ageRestricted"],
    [403, "IDENTITY_VERIFICATION_REQUIRED", "identityRequired"],
    [403, "LEGAL_RECONSENT_REQUIRED", "reconsentRequired"],
    [503, "CREATOR_PAYOUT_UNAVAILABLE", "unavailable"],
  ])("%i %s 는 %s 다", (status, code, expected) => {
    expect(toRequestPayoutFailure(apiError(status, { code }))).toBe(expected);
  });

  // 최소액 미만 422 는 금액을 함께 싣는다 — 덧붙은 칸이 있어도 코드로 가른다.
  it("최소액 미만 422 는 금액 칸이 붙어 있어도 최소액 미만이다", () => {
    const error = apiError(422, { code: "CREATOR_PAYOUT_BELOW_MINIMUM", minimumKrw: 10000, balanceKrw: 500 });
    expect(toRequestPayoutFailure(error)).toBe("belowMinimum");
  });

  // 정지 403 은 detail 이 문자열이다 — 코드만 보면 일반 실패로 접혀 "다시 시도"를 말하게 된다.
  it("정지 403 은 정지다", () => {
    expect(toRequestPayoutFailure(apiError(403, "Account suspended"))).toBe("suspended");
  });

  it("모르는 코드·네트워크 실패는 일반 실패다", () => {
    expect(toRequestPayoutFailure(apiError(500, undefined))).toBe("failed");
    expect(toRequestPayoutFailure(apiError(409, { code: "SOMETHING_ELSE" }))).toBe("failed");
    expect(toRequestPayoutFailure(new Error("network"))).toBe("failed");
  });
});

describe("REQUEST_PAYOUT_MESSAGES", () => {
  // 기다려도 풀리지 않는 거절에 "다시 시도"를 말하면 같은 버튼을 계속 누르게 된다.
  it("기다려서 풀리지 않는 거절은 다시 시도하라고 하지 않는다", () => {
    const permanent = [
      "infoRequired",
      "infoUnreadable",
      "inProgress",
      "nothingToPay",
      "belowMinimum",
      "notApproved",
      "identityRequired",
      "ageRestricted",
      "suspended",
    ] as const;
    for (const key of permanent) {
      expect(REQUEST_PAYOUT_MESSAGES[key]).not.toContain("다시 시도");
    }
  });
});
