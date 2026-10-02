import { describe, expect, it } from "vitest";

import { isContentRestrictedError } from "./contentRestricted";

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
