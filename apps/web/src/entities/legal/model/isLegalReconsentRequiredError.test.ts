import { describe, expect, it } from "vitest";

import { isLegalReconsentRequiredError } from "./isLegalReconsentRequiredError";

describe("isLegalReconsentRequiredError", () => {
  it("403 + {code: LEGAL_RECONSENT_REQUIRED}면 true다", () => {
    expect(
      isLegalReconsentRequiredError({
        status: 403,
        detail: { code: "LEGAL_RECONSENT_REQUIRED", kinds: ["terms"] },
        message: "재동의가 필요해요",
      }),
    ).toBe(true);
  });

  it("403이어도 detail이 string이면 false다 — 정지(Account suspended) 403과 구분돼야 한다", () => {
    expect(
      isLegalReconsentRequiredError({
        status: 403,
        detail: "Account suspended",
        message: "Account suspended",
      }),
    ).toBe(false);
  });

  it("403 + 다른 code면 false다", () => {
    expect(
      isLegalReconsentRequiredError({ status: 403, detail: { code: "다른값" }, message: "x" }),
    ).toBe(false);
  });

  it.each([401, 400, 500])("같은 detail이어도 상태코드가 403이 아니면(%d) false다", (status) => {
    expect(
      isLegalReconsentRequiredError({
        status,
        detail: { code: "LEGAL_RECONSENT_REQUIRED" },
        message: "x",
      }),
    ).toBe(false);
  });

  it("detail이 undefined면 false다", () => {
    expect(isLegalReconsentRequiredError({ status: 403, detail: undefined, message: "x" })).toBe(false);
  });
});
