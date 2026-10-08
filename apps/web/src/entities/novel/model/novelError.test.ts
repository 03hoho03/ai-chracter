import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { isContentNovelizeForbiddenError, isNovelizeNotAllowedError, toNovelLoadFailure } from "./novelError";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("isNovelizeNotAllowedError", () => {
  it("403 NOVELIZE_NOT_ALLOWED 만 참이다", () => {
    expect(isNovelizeNotAllowedError(apiError(403, { code: "NOVELIZE_NOT_ALLOWED" }))).toBe(true);
  });

  it.each([
    ["다른 코드의 403", apiError(403, { code: "NOVEL_FORBIDDEN" })],
    ["재동의 403", apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" })],
    ["문자열 detail 의 정지 403", apiError(403, "Account suspended")],
    ["같은 코드여도 403 이 아님", apiError(409, { code: "NOVELIZE_NOT_ALLOWED" })],
    ["detail 없음", apiError(403, undefined)],
    ["ApiError 가 아님", new Error("x")],
  ])("%s 는 거짓이다", (_, error) => {
    expect(isNovelizeNotAllowedError(error)).toBe(false);
  });
});

describe("isContentNovelizeForbiddenError", () => {
  it("403 CONTENT_NOVELIZE_FORBIDDEN 만 참이다", () => {
    expect(isContentNovelizeForbiddenError(apiError(403, { code: "CONTENT_NOVELIZE_FORBIDDEN" }))).toBe(true);
  });

  it.each([
    // 계정의 기능 허용 거절과는 서로 섞이지 않는다 — 화면이 다른 문구를 말해야 한다.
    ["계정의 기능 허용 거절", apiError(403, { code: "NOVELIZE_NOT_ALLOWED" })],
    ["작품 이용제한 403", apiError(403, { code: "CONTENT_RESTRICTED" })],
    ["재동의 403", apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" })],
    ["문자열 detail 의 남의 방 403", apiError(403, "Not the chat room owner")],
    ["같은 코드여도 403 이 아님", apiError(409, { code: "CONTENT_NOVELIZE_FORBIDDEN" })],
    ["detail 없음", apiError(403, undefined)],
    ["ApiError 가 아님", new Error("x")],
  ])("%s 는 거짓이다", (_, error) => {
    expect(isContentNovelizeForbiddenError(error)).toBe(false);
  });

  it("작품의 거절은 계정의 기능 허용 판정에 잡히지 않는다", () => {
    expect(isNovelizeNotAllowedError(apiError(403, { code: "CONTENT_NOVELIZE_FORBIDDEN" }))).toBe(false);
  });
});

describe("toNovelLoadFailure", () => {
  it("허용 없음은 잠김이다", () => {
    expect(toNovelLoadFailure(apiError(403, { code: "NOVELIZE_NOT_ALLOWED" }))).toBe("locked");
  });

  it("없는 소설과 남의 소설은 둘 다 찾을 수 없음이다", () => {
    expect(toNovelLoadFailure(apiError(404, { code: "NOVEL_NOT_FOUND" }))).toBe("missing");
    expect(toNovelLoadFailure(apiError(403, { code: "NOVEL_FORBIDDEN" }))).toBe("missing");
  });

  it("네트워크·서버 오류와 모르는 코드는 다시 시도할 수 있는 실패다", () => {
    expect(toNovelLoadFailure(apiError(0, undefined))).toBe("failed");
    expect(toNovelLoadFailure(apiError(500, undefined))).toBe("failed");
    expect(toNovelLoadFailure(apiError(404, "Not Found"))).toBe("failed");
  });
});
