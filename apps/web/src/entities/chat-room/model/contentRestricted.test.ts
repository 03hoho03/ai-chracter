import { describe, expect, it } from "vitest";

import {
  CONTENT_PRIVATE_START_MESSAGE,
  CONTENT_RESTRICTED_START_MESSAGE,
  isContentRestrictedError,
  toStartChatErrorMessage,
} from "./contentRestricted";

describe("isContentRestrictedError", () => {
  it("403 + {code: CONTENT_RESTRICTED}면 true다", () => {
    expect(isContentRestrictedError({ status: 403, detail: { code: "CONTENT_RESTRICTED" }, message: "x" })).toBe(true);
  });

  it("정지 403(detail 이 문자열)과 재동의 403(다른 code)은 false다", () => {
    expect(isContentRestrictedError({ status: 403, detail: "Account suspended", message: "x" })).toBe(false);
    expect(
      isContentRestrictedError({ status: 403, detail: { code: "LEGAL_RECONSENT_REQUIRED" }, message: "x" }),
    ).toBe(false);
  });

  it("같은 detail 이어도 403 이 아니면 false다", () => {
    expect(isContentRestrictedError({ status: 429, detail: { code: "CONTENT_RESTRICTED" }, message: "x" })).toBe(false);
  });
});

describe("toStartChatErrorMessage", () => {
  const fallback = "잠시 후 다시";

  it("이용제한 403 과 비공개 403 은 각자의 문구, 나머지는 호출부 문구다", () => {
    expect(toStartChatErrorMessage({ status: 403, detail: { code: "CONTENT_RESTRICTED" }, message: "x" }, fallback)).toBe(
      CONTENT_RESTRICTED_START_MESSAGE,
    );
    expect(toStartChatErrorMessage({ status: 403, detail: { code: "CONTENT_PRIVATE" }, message: "x" }, fallback)).toBe(
      CONTENT_PRIVATE_START_MESSAGE,
    );
    expect(toStartChatErrorMessage({ status: 403, detail: "Account suspended", message: "x" }, fallback)).toBe(fallback);
    expect(toStartChatErrorMessage({ status: 404, detail: { code: "CONTENT_PRIVATE" }, message: "x" }, fallback)).toBe(
      fallback,
    );
  });
});
