import { describe, expect, it } from "vitest";

import { PAYOUT_INFO_MESSAGES, toPayoutInfoFailure, toPayoutInfoFailureField } from "./payoutInfoResult";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "" };
}

describe("toPayoutInfoFailure", () => {
  it.each([
    [422, "CREATOR_PAYOUT_INFO_INVALID", "invalid"],
    [422, "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED", "foreigner"],
    [422, "CREATOR_PAYOUT_RRN_MISMATCH", "rrnMismatch"],
    [409, "CREATOR_PAYOUT_IN_PROGRESS", "inProgress"],
    [403, "CREATOR_PAYOUT_NOT_APPROVED", "notApproved"],
    [403, "CREATOR_PAYOUT_AGE_RESTRICTED", "ageRestricted"],
    [403, "IDENTITY_VERIFICATION_REQUIRED", "identityRequired"],
    [403, "LEGAL_RECONSENT_REQUIRED", "reconsentRequired"],
    [503, "CREATOR_PAYOUT_UNAVAILABLE", "unavailable"],
  ])("%i %s 는 %s 다", (status, code, expected) => {
    expect(toPayoutInfoFailure(apiError(status, { code }))).toBe(expected);
  });

  it("정지 403 은 정지다", () => {
    expect(toPayoutInfoFailure(apiError(403, "Account suspended"))).toBe("suspended");
  });

  it("모르는 코드·네트워크 실패는 일반 실패다", () => {
    expect(toPayoutInfoFailure(apiError(500, undefined))).toBe("failed");
    expect(toPayoutInfoFailure(apiError(422, { code: "SOMETHING_ELSE" }))).toBe("failed");
    expect(toPayoutInfoFailure(new Error("network"))).toBe("failed");
  });
});

describe("toPayoutInfoFailureField", () => {
  // 주민등록번호가 거절된 이유는 그 칸 아래에 붙어야 무엇을 고칠지 보인다.
  it("주민등록번호가 거절된 두 갈래만 그 칸에 붙인다", () => {
    expect(toPayoutInfoFailureField("foreigner")).toBe("rrn");
    expect(toPayoutInfoFailureField("rrnMismatch")).toBe("rrn");
    expect(toPayoutInfoFailureField("invalid")).toBeNull();
    expect(toPayoutInfoFailureField("inProgress")).toBeNull();
  });
});

describe("PAYOUT_INFO_MESSAGES", () => {
  it("기다려서 풀리지 않는 거절은 다시 시도하라고 하지 않는다", () => {
    const permanent = [
      "invalid",
      "foreigner",
      "rrnMismatch",
      "inProgress",
      "notApproved",
      "identityRequired",
      "ageRestricted",
      "suspended",
    ] as const;
    for (const key of permanent) {
      expect(PAYOUT_INFO_MESSAGES[key]).not.toContain("다시 시도");
    }
  });
});
