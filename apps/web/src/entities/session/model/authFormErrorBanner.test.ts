import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { getAuthFormErrorBanner } from "./authFormErrorBanner";
import { SUSPENDED_ERROR_MESSAGE } from "./suspendedMessage";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getAuthFormErrorBanner — onboarding-google", () => {
  it("400(토큰 만료·이중 사용)은 처음부터 다시 하라고 안내하고 로그인 링크를 준다", () => {
    expect(getAuthFormErrorBanner(apiError(400, "Invalid or expired token"), "onboarding-google")).toEqual({
      message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.",
      showsLoginLink: true,
    });
  });

  it("409(탈퇴 1년 재가입 차단)는 '1년'을 명시한다", () => {
    const banner = getAuthFormErrorBanner(apiError(409, "Email already registered"), "onboarding-google");

    expect(banner?.message).toContain("1년");
    expect(banner?.showsLoginLink).toBe(true);
  });

  it("403 정지는 로그인 화면과 같은 정지 문구다(사본이 아니라 같은 상수)", () => {
    expect(getAuthFormErrorBanner(apiError(403, "Account suspended"), "onboarding-google")).toEqual({
      message: SUSPENDED_ERROR_MESSAGE,
      showsLoginLink: true,
    });
  });

  it.each([
    ["500", apiError(500)],
    ["422", apiError(422)],
    ["네트워크(status 0)", apiError(0)],
    ["ApiError가 아닌 예외", new Error("boom")],
  ])("판별할 수 없는 실패(%s)는 null — 호출부가 기존 fallback으로 보낸다", (_label, error) => {
    expect(getAuthFormErrorBanner(error, "onboarding-google")).toBeNull();
  });
});

describe("getAuthFormErrorBanner — change-password", () => {
  it("401은 세션 만료로 안내하고 로그인 링크를 준다", () => {
    expect(getAuthFormErrorBanner(apiError(401, "Not authenticated"), "change-password")).toEqual({
      message: "세션이 만료됐어요. 다시 로그인해주세요.",
      showsLoginLink: true,
    });
  });

  it("403 정지는 정지 문구이고, 다시 로그인해도 막히므로 로그인 링크를 주지 않는다", () => {
    expect(getAuthFormErrorBanner(apiError(403, "Account suspended"), "change-password")).toEqual({
      message: SUSPENDED_ERROR_MESSAGE,
      showsLoginLink: false,
    });
  });

  it("정지가 아닌 403(재동의 게이트)을 정지로 오분류하지 않는다", () => {
    const error = apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" });

    expect(getAuthFormErrorBanner(error, "change-password")).toBeNull();
  });

  it("400(현재 비밀번호 오답)은 기존 문구 그대로다", () => {
    expect(getAuthFormErrorBanner(apiError(400, "Current password is incorrect"), "change-password")).toEqual({
      message: "현재 비밀번호가 올바르지 않아요.",
      showsLoginLink: false,
    });
  });

  it("500은 null", () => {
    expect(getAuthFormErrorBanner(apiError(500), "change-password")).toBeNull();
  });
});

describe("getAuthFormErrorBanner — J-1 회귀", () => {
  it.each([
    [400, "onboarding-google"],
    [409, "onboarding-google"],
    [403, "onboarding-google"],
    [400, "change-password"],
    [401, "change-password"],
    [403, "change-password"],
  ] as const)("%d(%s) 문구는 '잠시 후'라고 말하지 않는다 — 기다려도 풀리지 않는 실패다", (status, surface) => {
    const banner = getAuthFormErrorBanner(apiError(status, "Account suspended"), surface);

    expect(banner).not.toBeNull();
    expect(banner?.message).not.toContain("잠시 후");
  });
});
