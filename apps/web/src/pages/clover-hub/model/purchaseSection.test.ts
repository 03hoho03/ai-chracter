import { describe, expect, it } from "vitest";

import { getPurchaseSection } from "./purchaseSection";

describe("getPurchaseSection", () => {
  it("결제가 꺼져 있으면 회원 상태와 무관하게 준비 중이다", () => {
    expect(getPurchaseSection(false, { purchaseBlockReason: null })).toBe("disabled");
  });

  it("살 수 있으면 상품을 보인다", () => {
    expect(getPurchaseSection(true, { purchaseBlockReason: null })).toBe("products");
  });

  it("본인인증 전이면 인증 안내다", () => {
    expect(getPurchaseSection(true, { purchaseBlockReason: "identity_required" })).toBe("identityRequired");
  });

  // 인증된 미성년에게 상품을 보이면 다이얼로그를 다 채운 뒤에야 나이 거절을 받는다.
  it("만 19세 미만이면 상품 대신 나이 안내다", () => {
    expect(getPurchaseSection(true, { purchaseBlockReason: "age_restricted" })).toBe("ageRestricted");
  });

  it("세션을 못 읽었으면 살 수 있다고 보지 않는다", () => {
    expect(getPurchaseSection(true, undefined)).toBe("identityRequired");
  });
});
