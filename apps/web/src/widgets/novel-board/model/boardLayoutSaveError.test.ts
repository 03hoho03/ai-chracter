import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toBoardLayoutSaveFailure } from "./boardLayoutSaveError";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, message: "x", detail });
}

describe("toBoardLayoutSaveFailure", () => {
  it("크기 초과 422 는 조용히 건너뛴다", () => {
    expect(toBoardLayoutSaveFailure(apiError(422, { code: "NOVEL_BOARD_LAYOUT_TOO_LARGE" }))).toBe("skip");
  });

  it("재동의 403 은 전역 모달에 맡긴다", () => {
    expect(toBoardLayoutSaveFailure(apiError(403, { code: "LEGAL_RECONSENT_REQUIRED" }))).toBe("skip");
  });

  it.each([
    ["서버 오류", apiError(500, undefined)],
    ["끊긴 연결", apiError(0, undefined)],
    ["다른 422", apiError(422, { code: "OTHER" })],
    ["ApiError 가 아님", new Error("x")],
  ])("%s 는 알린다", (_, error) => {
    expect(toBoardLayoutSaveFailure(error)).toBe("notify");
  });
});
