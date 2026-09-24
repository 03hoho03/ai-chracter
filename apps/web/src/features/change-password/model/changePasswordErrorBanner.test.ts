import { describe, expect, it } from "vitest";

import { SUSPENDED_ERROR_MESSAGE } from "@/entities/session";
import { ApiErrorObject } from "@/shared/api/client";

import { getChangePasswordErrorBanner } from "./changePasswordErrorBanner";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getChangePasswordErrorBanner", () => {
  it("401은 세션 만료로 안내하고 로그인 링크를 준다", () => {
    expect(getChangePasswordErrorBanner(apiError(401, "Not authenticated"))).toEqual({
      message: "세션이 만료됐어요. 다시 로그인해주세요.",
      shouldShowLoginLink: true,
    });
  });

  it("403 정지는 정지 문구이고, 다시 로그인해도 막히므로 로그인 링크를 주지 않는다", () => {
    expect(getChangePasswordErrorBanner(apiError(403, "Account suspended"))).toEqual({
      message: SUSPENDED_ERROR_MESSAGE,
      shouldShowLoginLink: false,
    });
  });

  it("400(현재 비밀번호 오답)은 기존 문구 그대로다", () => {
    expect(getChangePasswordErrorBanner(apiError(400, "Current password is incorrect"))).toEqual({
      message: "현재 비밀번호가 올바르지 않아요.",
      shouldShowLoginLink: false,
    });
  });

  it("500은 undefined", () => {
    expect(getChangePasswordErrorBanner(apiError(500))).toBeUndefined();
  });

  // 403을 status만으로 정지로 읽는 회귀는 온보딩 폼과 같은 오분류다(review-S7 ⚪-1).
  it("정지가 아닌 403(재동의 게이트)을 정지로 오분류하지 않는다", () => {
    const error = apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" });

    expect(getChangePasswordErrorBanner(error)).toBeUndefined();
  });

  it.each([400, 401, 403])("%d 문구는 '잠시 후'라고 말하지 않는다 — 기다려도 풀리지 않는 실패다(J-1)", (status) => {
    const banner = getChangePasswordErrorBanner(apiError(status, "Account suspended"));

    expect(banner).toBeDefined();
    expect(banner?.message).not.toContain("잠시 후");
  });
});
