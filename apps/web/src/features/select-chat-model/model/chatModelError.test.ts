import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  CHAT_MODEL_NOT_ALLOWED_MESSAGE,
  isChatModelNotAllowedError,
  PREVIEW_CHAT_MODEL_NOT_ALLOWED_MESSAGE,
} from "./chatModelError";

// 서버는 계정이 아니라 지금 채팅에서 보이는 모델인지로 판정한다 — 계정 탓으로 읽히는 문장을 쓰지 않는다.
describe("모델을 쓸 수 없다는 403 문장", () => {
  it("계정을 말하지 않는다", () => {
    expect(CHAT_MODEL_NOT_ALLOWED_MESSAGE).not.toContain("계정");
    expect(PREVIEW_CHAT_MODEL_NOT_ALLOWED_MESSAGE).not.toContain("계정");
  });

  // 미리보기는 고른 모델을 기본 모델로 되돌리므로 그 사실을, 대화방은 목록을 다시 불러오므로 그 사실을 말한다.
  it("대화방과 미리보기가 각자 뒤에 일어난 일을 말한다", () => {
    expect(CHAT_MODEL_NOT_ALLOWED_MESSAGE).toContain("목록");
    expect(PREVIEW_CHAT_MODEL_NOT_ALLOWED_MESSAGE).toContain("기본 모델");
  });
});

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
