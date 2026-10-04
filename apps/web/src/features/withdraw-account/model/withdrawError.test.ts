import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { getWithdrawError, WITHDRAW_GENERIC_ERROR_MESSAGE } from "./withdrawError";

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getWithdrawError", () => {
  it("400 비밀번호 오답은 칸 아래 오류다", () => {
    expect(getWithdrawError(apiError(400, "Current password is incorrect"))).toEqual({
      target: "field",
      message: "현재 비밀번호가 올바르지 않아요.",
    });
  });

  it("429 AUTH_LIMIT 는 칸 오류가 아니라 기다릴 분을 말하는 토스트다", () => {
    const error = apiError(429, { code: "AUTH_LIMIT", retryAfterSeconds: 300, window: "auth" });

    expect(getWithdrawError(error)).toEqual({
      target: "toast",
      message: "비밀번호 확인을 너무 많이 시도했어요 · 약 5분 뒤에 다시 시도할 수 있어요",
    });
  });

  it.each([
    apiError(400, "다른 사유"),
    apiError(429, "Too Many Requests"),
    apiError(500),
    new Error("network"),
  ])("그 밖의 실패는 일반 오류 토스트다 (%#)", (error) => {
    expect(getWithdrawError(error)).toEqual({ target: "toast", message: WITHDRAW_GENERIC_ERROR_MESSAGE });
  });
});
