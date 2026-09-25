import { describe, expect, it } from "vitest";

import { SUSPENDED_ERROR_MESSAGE } from "@/entities/session";
import { ApiErrorObject } from "@/shared/api/client";

import { getOnboardingErrorBanner } from "./onboardingErrorBanner";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getOnboardingErrorBanner", () => {
  it("400(토큰 만료·이중 사용)은 처음부터 다시 하라고 안내하고 로그인 링크를 준다", () => {
    expect(getOnboardingErrorBanner(apiError(400, "Invalid or expired token"))).toEqual({
      message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.",
      shouldShowLoginLink: true,
    });
  });

  it("409(탈퇴 1년 재가입 차단)는 '1년'을 명시한다", () => {
    const banner = getOnboardingErrorBanner(apiError(409, "Email already registered"));

    expect(banner?.message).toContain("1년");
    expect(banner?.shouldShowLoginLink).toBe(true);
  });

  it("403 정지는 로그인 화면과 같은 정지 문구다(사본이 아니라 같은 상수)", () => {
    expect(getOnboardingErrorBanner(apiError(403, "Account suspended"))).toEqual({
      message: SUSPENDED_ERROR_MESSAGE,
      shouldShowLoginLink: true,
    });
  });

  it.each([
    ["500", apiError(500)],
    ["422", apiError(422)],
    ["네트워크(status 0)", apiError(0)],
    ["ApiError가 아닌 예외", new Error("boom")],
  ])("판별할 수 없는 실패(%s)는 undefined — 호출부가 기존 fallback으로 보낸다", (_label, error) => {
    expect(getOnboardingErrorBanner(error)).toBeUndefined();
  });

  // 온보딩 라우트는 지금 재동의 게이트를 거치지 않지만, 403을 status만으로 정지로 읽는 회귀는
  // 비밀번호 변경 폼과 같은 오분류다.
  it("정지가 아닌 403(재동의 게이트)을 정지로 오분류하지 않는다", () => {
    const error = apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" });

    expect(getOnboardingErrorBanner(error)).toBeUndefined();
  });

  it.each([400, 409, 403])("%d 문구는 '잠시 후'라고 말하지 않는다 — 기다려도 풀리지 않는 실패다", (status) => {
    const banner = getOnboardingErrorBanner(apiError(status, "Account suspended"));

    expect(banner).toBeDefined();
    expect(banner?.message).not.toContain("잠시 후");
  });
});
