import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { isChatModelNotAllowedError } from "./chatModelError";

describe("isChatModelNotAllowedError", () => {
  it("상위 모델 허용이 없다는 403 이면 참이다", () => {
    const error = new ApiErrorObject({ status: 403, message: "x", detail: { code: "CHAT_MODEL_NOT_ALLOWED" } });
    expect(isChatModelNotAllowedError(error)).toBe(true);
  });

  // 정지 403 은 `detail` 이 문자열이다 — 같은 403 이라도 허용 문제가 아니다.
  it("다른 403 은 거짓이다", () => {
    expect(isChatModelNotAllowedError(new ApiErrorObject({ status: 403, message: "x", detail: "suspended" }))).toBe(false);
    expect(
      isChatModelNotAllowedError(new ApiErrorObject({ status: 403, message: "x", detail: { code: "NOVELIZE_NOT_ALLOWED" } })),
    ).toBe(false);
  });
});
