import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { classifyClaimError } from "./claimError";

function apiError(status: number, detail?: string | Record<string, unknown>) {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("classifyClaimError", () => {
  // 응답이 없으면 지급됐는지 모른다 — 판을 다시 받아 확인한다.
  it("응답이 없는 실패(상태 0)는 확인 중이다", () => {
    expect(classifyClaimError(apiError(0))).toBe("checking");
  });

  // 정지 스위치의 503 은 지급이 안 된 것이 확실하다. 같은 5xx 대역이라 그 밖의 서버 오류보다 먼저 가른다.
  it("정지 스위치의 503 은 잠시 멈춤이다", () => {
    expect(classifyClaimError(apiError(503, { code: "CLOVER_PAUSED" }))).toBe("paused");
  });

  it.each([
    ["다른 코드의 503", apiError(503, { code: "SOMETHING_ELSE" })],
    ["문자열 detail 의 503", apiError(503, "Service Unavailable")],
    ["500", apiError(500)],
    ["502", apiError(502)],
  ])("%s 는 지급 여부를 모르므로 확인 중이다", (_, error) => {
    expect(classifyClaimError(error)).toBe("checking");
  });

  it("본인인증이 필요하다는 403 은 인증 안내다", () => {
    expect(classifyClaimError(apiError(403, { code: "IDENTITY_VERIFICATION_REQUIRED" }))).toBe("identity");
  });

  // 같은 403 을 쓰는 다른 거절에 인증 안내를 띄우면 이용자가 엉뚱한 일을 하러 간다.
  it.each([
    ["문자열 detail 의 정지 403", apiError(403, "Account suspended")],
    ["재동의 403", apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" })],
  ])("%s 는 확정 실패다", (_, error) => {
    expect(classifyClaimError(error)).toBe("failed");
  });

  it("스위치가 꺼진 404 는 찾을 수 없는 화면이다", () => {
    expect(classifyClaimError(apiError(404))).toBe("off");
  });

  it.each([
    ["400", apiError(400)],
    ["401", apiError(401)],
    ["422", apiError(422)],
  ])("그 밖의 %s 는 확정 실패다", (_, error) => {
    expect(classifyClaimError(error)).toBe("failed");
  });

  it.each([
    ["Error", new Error("x")],
    ["undefined", undefined],
  ])("ApiError 가 아닌 값(%s)은 확정 실패다", (_, error) => {
    expect(classifyClaimError(error)).toBe("failed");
  });
});
