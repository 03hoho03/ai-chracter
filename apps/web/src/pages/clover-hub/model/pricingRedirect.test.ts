import { describe, expect, it } from "vitest";

import { cloverPricingRedirectSearchSchema, toCloverHubSearch } from "./pricingRedirect";

function redirectSearchOf(raw: Record<string, unknown>) {
  return toCloverHubSearch(cloverPricingRedirectSearchSchema.parse(raw));
}

describe("옛 상품 안내 주소의 충전 화면 넘기기", () => {
  // 옛 화면에서 고른 상품이 넘어가야 충전 화면이 그 상품을 이어 받는다.
  it("고른 상품 키를 그대로 가져간다", () => {
    expect(redirectSearchOf({ product: "mini" })).toEqual({ product: "mini" });
  });

  it("상품 키가 없으면 빈 서치다", () => {
    expect(redirectSearchOf({})).toEqual({});
  });

  it("옛 화면이 읽지 않던 파라미터는 가져가지 않는다", () => {
    expect(redirectSearchOf({ product: "lite", utm_source: "x" })).toEqual({ product: "lite" });
  });

  // 라우터가 숫자만인 쿼리 값을 숫자로 준다 — 던지면 앱 크롬 없는 오류 상자가 뜬다.
  it("문자열이 아닌 상품 값은 부재로 접는다", () => {
    expect(redirectSearchOf({ product: 1 })).toEqual({});
  });
});
