import { describe, expect, it } from "vitest";

import { isWebnovelOpen } from "./webnovelOpen";

describe("isWebnovelOpen", () => {
  it("모두에게 열려 있으면 세션과 무관하게 연다", () => {
    expect(isWebnovelOpen(true, undefined)).toBe(true);
    expect(isWebnovelOpen(true, false)).toBe(true);
  });

  it("미리보기 명단 회원이면 공개 응답이 닫힘이어도 연다", () => {
    expect(isWebnovelOpen(false, true)).toBe(true);
  });

  it("둘 다 닫힘이거나 아직 모르면 닫는다", () => {
    expect(isWebnovelOpen(false, false)).toBe(false);
    expect(isWebnovelOpen(false, undefined)).toBe(false);
    expect(isWebnovelOpen(undefined, undefined)).toBe(false);
  });
});
