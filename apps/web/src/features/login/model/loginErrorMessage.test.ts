import { describe, expect, it } from "vitest";

import { SUSPENDED_ERROR_MESSAGE } from "@/entities/session";
import { ApiErrorObject } from "@/shared/api/client";

import {
  GENERIC_LOGIN_ERROR_MESSAGE,
  getLoginErrorMessage,
  getLoginSubmitErrorMessage,
  LOGIN_ERROR_CODES,
  MINIMUM_AGE_ERROR_MESSAGE,
  SIGNUP_METHODS,
  UNKNOWN_LOGIN_ERROR,
  type LoginErrorCode,
} from "./loginErrorMessage";

const CANCELLED_CODES: readonly LoginErrorCode[] = ["google_cancelled", "kakao_cancelled"];

describe("getLoginErrorMessage", () => {
  // 목록이 백엔드와 맞는지는 여기서 검사하지 않는다(백엔드 코드는 OpenAPI에 실리지 않는다). 여기서 지키는 것은
  // FE가 아는 코드마다 일반 오류가 아닌 자기 문구가 있다는 것이다.
  it.each(LOGIN_ERROR_CODES.filter((code) => !CANCELLED_CODES.includes(code)))(
    "알려진 코드 %s 는 일반 오류가 아닌 자기 문구를 가진다",
    (code) => {
      const message = getLoginErrorMessage(code);

      expect(message).toBeTruthy();
      expect(message).not.toBe(GENERIC_LOGIN_ERROR_MESSAGE);
    },
  );

  it.each(CANCELLED_CODES)("%s 는 사용자가 스스로 취소한 것이라 배너를 띄우지 않는다", (code) => {
    expect(getLoginErrorMessage(code)).toBeNull();
  });

  it("목록 밖 코드는 일반 오류 문구로 떨어진다", () => {
    expect(getLoginErrorMessage(UNKNOWN_LOGIN_ERROR)).toBe(GENERIC_LOGIN_ERROR_MESSAGE);
  });

  it("state 만료와 교환 실패는 제공자 이름을 말한다", () => {
    expect(getLoginErrorMessage("google_state")).toContain("구글");
    expect(getLoginErrorMessage("kakao_state")).toContain("카카오");
    expect(getLoginErrorMessage("google_failed")).toContain("구글");
    expect(getLoginErrorMessage("kakao_failed")).toContain("카카오");
  });

  it("정지는 로그인 폼과 같은 정지 문구다(사본이 아니라 같은 상수)", () => {
    expect(getLoginErrorMessage("account_suspended")).toBe(SUSPENDED_ERROR_MESSAGE);
  });

  it("카카오 이메일 없음은 카카오계정에서 이메일을 인증하라는 해결 방법을 준다", () => {
    const message = getLoginErrorMessage("kakao_email_required");

    expect(message).toContain("카카오계정");
    expect(message).toContain("인증");
  });

  it("구글 이메일 미인증은 구글 계정에서 이메일을 인증하라는 해결 방법을 준다", () => {
    const message = getLoginErrorMessage("google_email_required");

    expect(message).toContain("구글");
    expect(message).toContain("인증");
  });

  describe("이미 가입된 이메일", () => {
    it("kakao_email_taken 은 method 마다 서로 다른 문구이고 어느 것도 일반 오류가 아니다", () => {
      const messages = SIGNUP_METHODS.map((method) => getLoginErrorMessage("kakao_email_taken", method));

      expect(new Set(messages).size).toBe(SIGNUP_METHODS.length);
      expect(messages).not.toContain(GENERIC_LOGIN_ERROR_MESSAGE);
    });

    it("kakao_email_taken 은 가입된 방법으로 로그인하라고 한다", () => {
      expect(getLoginErrorMessage("kakao_email_taken", "email")).toBe(
        "이미 이메일·비밀번호로 가입된 계정이 있어요. 이메일과 비밀번호로 로그인해주세요.",
      );
      expect(getLoginErrorMessage("kakao_email_taken", "google")).toContain("구글로 가입된");
      expect(getLoginErrorMessage("kakao_email_taken", "kakao")).toContain("다른 카카오계정");
    });

    it("google_email_taken + method=kakao 는 카카오 로그인을 이용하라고 한다", () => {
      expect(getLoginErrorMessage("google_email_taken", "kakao")).toBe(
        "이미 카카오로 가입된 이메일이에요. 카카오 로그인을 이용해주세요.",
      );
    });

    it("method 가 빠져도 일반 오류가 아니라 '처음 가입한 방법'으로 안내한다", () => {
      expect(getLoginErrorMessage("kakao_email_taken")).toContain("처음 가입한 방법");
      expect(getLoginErrorMessage("google_email_taken")).toContain("처음 가입한 방법");
    });
  });
});

function apiError(status: number, detail: string | Record<string, unknown> = "x") {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("getLoginSubmitErrorMessage", () => {
  // 맞는 비밀번호여도 상한을 넘으면 429 다 — 일반 오류나 오답 문구로 보이면 사용자는 같은 시도를 되풀이한다.
  it("429 AUTH_LIMIT 는 기다릴 분을 올림으로 말한다", () => {
    const message = getLoginSubmitErrorMessage(
      apiError(429, { code: "AUTH_LIMIT", retryAfterSeconds: 61, window: "auth" }),
    );

    expect(message).toBe("로그인 시도가 너무 많았어요 · 약 2분 뒤에 다시 시도할 수 있어요");
  });

  it("모양이 다른 429 는 일반 오류로 떨어진다", () => {
    expect(getLoginSubmitErrorMessage(apiError(429, "Too Many Requests"))).toBe(GENERIC_LOGIN_ERROR_MESSAGE);
  });

  it.each([
    [apiError(401, "Invalid credentials"), "이메일 또는 비밀번호가 올바르지 않습니다."],
    [apiError(403, "Account suspended"), SUSPENDED_ERROR_MESSAGE],
    [apiError(403, "Minimum age not met"), MINIMUM_AGE_ERROR_MESSAGE],
    [apiError(500), GENERIC_LOGIN_ERROR_MESSAGE],
    [new Error("network"), GENERIC_LOGIN_ERROR_MESSAGE],
  ])("기존 분기 문구는 그대로다 (%#)", (error, expected) => {
    expect(getLoginSubmitErrorMessage(error)).toBe(expected);
  });

  it("그 밖의 403 은 이메일 미인증 안내다", () => {
    expect(getLoginSubmitErrorMessage(apiError(403, "Email not verified"))).toContain("이메일 인증이 완료되지 않은");
  });
});
