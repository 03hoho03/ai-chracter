import { describe, expect, it } from "vitest";

import { buildPaymentRedirectUrl } from "./paymentRedirectUrl";

describe("buildPaymentRedirectUrl", () => {
  it("복귀 주소가 없으면 충전 화면 주소 그대로다", () => {
    expect(buildPaymentRedirectUrl("https://ddona.site", undefined)).toBe("https://ddona.site/clover");
  });

  // 결제창이 페이지를 떠났다 돌아와도 "대화로 돌아가기"가 갈 곳을 잃지 않게 쿼리에 싣는다.
  it("복귀 주소를 인코딩해 쿼리에 싣는다", () => {
    const url = buildPaymentRedirectUrl("https://ddona.site", "/chat/room-1?x=1&y=2");
    expect(url).toBe("https://ddona.site/clover?returnTo=%2Fchat%2Froom-1%3Fx%3D1%26y%3D2");
    expect(new URL(url).searchParams.get("returnTo")).toBe("/chat/room-1?x=1&y=2");
  });
});
