import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toIdentityErrorResult } from "./identityResult";

function apiError(status: number, code: string) {
  return new ApiErrorObject({ status, message: "x", detail: { code } });
}

function messageOf(error: unknown): string {
  const result = toIdentityErrorResult(error);
  return result.kind === "notice" ? result.message : "";
}

describe("toIdentityErrorResult", () => {
  // 서버가 아무것도 저장하지 않은 거절은 그 사실을 함께 말한다.
  it.each([
    ["14세 미만", apiError(403, "IDENTITY_UNDER_MINIMUM_AGE"), "14세"],
    ["CI 없음", apiError(422, "IDENTITY_CI_MISSING"), "저장하지 않았어요"],
    ["생년월일 없음", apiError(422, "IDENTITY_BIRTH_DATE_MISSING"), "저장하지 않았어요"],
    ["다른 계정에서 인증", apiError(409, "IDENTITY_ALREADY_USED"), "다른 계정"],
  ])("%s 는 그 이유를 말한다", (_, error, expected) => {
    expect(messageOf(error)).toContain(expected);
  });

  it("14세 미만도 저장하지 않았다고 말한다", () => {
    expect(messageOf(apiError(403, "IDENTITY_UNDER_MINIMUM_AGE"))).toContain("저장하지 않았어요");
  });

  // 같은 409 라도 이미 인증한 계정은 실패가 아니다(다른 탭에서 마쳤다).
  it("이미 인증한 계정은 중립 안내다", () => {
    const result = toIdentityErrorResult(apiError(409, "IDENTITY_ALREADY_VERIFIED"));
    expect(result).toMatchObject({ kind: "notice", tone: "neutral" });
  });

  it("모르는 실패는 일반 문구이고 서버 문구를 보이지 않는다", () => {
    const error = new ApiErrorObject({ status: 500, message: "Internal Server Error", detail: "boom" });
    expect(messageOf(error)).not.toContain("boom");
    expect(toIdentityErrorResult(error)).toMatchObject({ tone: "error" });
  });
});
