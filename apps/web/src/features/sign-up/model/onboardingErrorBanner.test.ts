import { describe, expect, it } from "vitest";

import { SUSPENDED_ERROR_MESSAGE } from "@/entities/session";
import { ApiErrorObject } from "@/shared/api/client";

import { getOnboardingErrorBanner } from "./onboardingErrorBanner";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getOnboardingErrorBanner", () => {
  it("400(가입 대기 쿠키 만료·없음)은 처음부터 다시 하라고 안내하고 로그인 링크를 준다", () => {
    expect(getOnboardingErrorBanner(apiError(400, "Invalid or expired token"))).toEqual({
      message: "인증이 만료되었어요. 처음부터 다시 시도해주세요.",
      shouldShowLoginLink: true,
    });
  });

  it("409 REREGISTRATION_BLOCKED(탈퇴 1년 재가입 차단)는 '1년'을 명시한다", () => {
    const banner = getOnboardingErrorBanner(apiError(409, { code: "REREGISTRATION_BLOCKED" }));

    expect(banner?.message).toContain("1년");
    expect(banner?.message).not.toContain("이미 가입된");
    expect(banner?.shouldShowLoginLink).toBe(true);
  });

  it("409 EMAIL_ALREADY_REGISTERED(그사이 같은 이메일 가입)는 이미 가입됐으니 로그인하라고 한다", () => {
    const banner = getOnboardingErrorBanner(apiError(409, { code: "EMAIL_ALREADY_REGISTERED" }));

    expect(banner?.message).toContain("이미 가입된 이메일");
    expect(banner?.message).not.toContain("1년");
    expect(banner?.shouldShowLoginLink).toBe(true);
  });

  it.each([
    ["모르는 code", { code: "SOMETHING_NEW" }],
    ["code 없는 문자열 detail", "Email already registered"],
  ])("409 인데 %s 면 토스트로 떨어뜨리지 않고 두 사정을 함께 덮는 문구를 준다", (_label, detail) => {
    const banner = getOnboardingErrorBanner(apiError(409, detail));

    expect(banner?.message).toContain("이미 가입됐거나");
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
