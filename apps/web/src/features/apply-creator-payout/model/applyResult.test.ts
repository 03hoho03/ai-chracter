import { describe, expect, it } from "vitest";

import { APPLY_MESSAGES, toApplyFailure } from "./applyResult";

function apiError(status: number, detail: unknown) {
  return { status, detail, message: "" };
}

describe("toApplyFailure", () => {
  it.each([
    [403, "IDENTITY_VERIFICATION_REQUIRED", "identityRequired"],
    [403, "CREATOR_PAYOUT_AGE_RESTRICTED", "ageRestricted"],
    [422, "CREATOR_PAYOUT_NO_PUBLISHED_WORK", "noPublishedWork"],
    [409, "CREATOR_PAYOUT_ALREADY_APPLIED", "alreadyApplied"],
    [403, "LEGAL_RECONSENT_REQUIRED", "reconsentRequired"],
    [503, "CREATOR_PAYOUT_UNAVAILABLE", "unavailable"],
  ])("%i %s 는 %s 다", (status, code, expected) => {
    expect(toApplyFailure(apiError(status, { code }))).toBe(expected);
  });

  // 정지 403 은 detail 이 문자열이다 — 코드만 보면 일반 실패로 접혀 "다시 시도"를 말하게 된다.
  it("정지 403 은 정지다", () => {
    expect(toApplyFailure(apiError(403, "Account suspended"))).toBe("suspended");
  });

  it("모르는 코드·네트워크 실패는 일반 실패다", () => {
    expect(toApplyFailure(apiError(500, undefined))).toBe("failed");
    expect(toApplyFailure(apiError(409, { code: "SOMETHING_ELSE" }))).toBe("failed");
    expect(toApplyFailure(new Error("network"))).toBe("failed");
  });
});

describe("APPLY_MESSAGES", () => {
  // 자격·정지·중복은 기다려도 풀리지 않는다 — "다시 시도"를 말하면 같은 버튼을 계속 누르게 된다.
  it("기다려서 풀리지 않는 거절은 다시 시도하라고 하지 않는다", () => {
    for (const key of ["identityRequired", "ageRestricted", "noPublishedWork", "alreadyApplied", "suspended"] as const) {
      expect(APPLY_MESSAGES[key]).not.toContain("다시 시도");
    }
  });
});
