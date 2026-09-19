import { describe, expect, it } from "vitest";

import { formatCloverSpendConfirmDescription } from "./confirmCloverSpendCopy";

describe("formatCloverSpendConfirmDescription", () => {
  // 🔴 이 두 케이스가 이 함수의 존재 이유다(S12 후속). 한 문구를 공유했을 때 이미지에서
  // "자정"이 최대 24시간짜리 거짓이었다 — 이미지 무료분은 시간당 충전이다
  // (BE `IMAGE_TOKEN_REFILL_SECONDS = 3600`). 둘을 같은 문자열로 되돌리면 한쪽이 빨개진다.
  it("채팅은 자정을 말한다 — KST 일일 키라 참이다", () => {
    const text = formatCloverSpendConfirmDescription("chat", 10);
    expect(text).toContain("자정");
    expect(text).toContain("10개씩");
  });

  it("이미지는 자정을 말하지 않는다 — 시간당 충전이라 거짓이 된다", () => {
    const text = formatCloverSpendConfirmDescription("image", 30);
    expect(text).not.toContain("자정");
    expect(text).toContain("30개씩");
  });

  // 시점을 약속하지 않는다는 것이 이미지 문구의 규범이다(clover-techspec.md CT-8-2,
  // `imageRateLimitMessage.ts`가 같은 이유로 `retryAfterSeconds`를 안 쓴다).
  it("이미지 문구가 구체적 시점을 약속하지 않는다", () => {
    const text = formatCloverSpendConfirmDescription("image", 30);
    expect(text).not.toMatch(/\d+\s*(분|시간)\s*뒤/);
  });
});
