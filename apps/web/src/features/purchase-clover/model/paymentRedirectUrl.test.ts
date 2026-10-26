import { describe, expect, it } from "vitest";

import { buildPaymentRedirectUrl } from "./paymentRedirectUrl";

describe("buildPaymentRedirectUrl", () => {
  // 결제창은 돌아올 주소에 결제 결과 쿼리를 덧붙인다. 주소에 쿼리가 이미 있으면 덧붙이는 방식에 따라 결과 쿼리가 앞
  // 값에 먹혀 결제 확정이 사라질 수 있어, 쿼리 없는 충전 화면 주소만 넘긴다(복귀 주소는 탭 저장소가 나른다).
  it("쿼리 없는 충전 화면 주소다", () => {
    const url = buildPaymentRedirectUrl("https://ddona.site");
    expect(url).toBe("https://ddona.site/clover");
    expect(new URL(url).search).toBe("");
  });
});
