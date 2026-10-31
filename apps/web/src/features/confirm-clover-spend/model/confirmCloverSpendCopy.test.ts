import { describe, expect, it } from "vitest";

import { formatCloverSpendConfirmDescription } from "./confirmCloverSpendCopy";

describe("formatCloverSpendConfirmDescription", () => {
  // 채팅에는 하루 무료 대화가 없다 — "무료 한도를 다 썼다"도 "자정에 다시 열린다"도 거짓이다. 본인인증을
  // 해도 받는 것은 무료 대화가 아니라 출석·미션 클로버라 누구에게나 같은 문장이다.
  it("채팅은 무료 대화·자정을 말하지 않고 차감만 말한다", () => {
    const text = formatCloverSpendConfirmDescription("chat", 10);
    expect(text).not.toContain("무료");
    expect(text).not.toContain("자정");
    expect(text).toContain("10개씩");
  });

  // 이미지 무료분은 시간당 충전이라 "자정"이 최대 24시간짜리 거짓이다(BE `IMAGE_TOKEN_REFILL_SECONDS = 3600`).
  it("이미지는 자정을 말하지 않는다 — 시간당 충전이라 거짓이 된다", () => {
    const text = formatCloverSpendConfirmDescription("image", 30);
    expect(text).not.toContain("자정");
    expect(text).toContain("30개씩");
  });

  // 시점을 약속하지 않는다는 것이 이미지 문구의 규범이다
  // (`imageRateLimitMessage.ts`가 같은 이유로 `retryAfterSeconds`를 안 쓴다).
  it("이미지 문구가 구체적 시점을 약속하지 않는다", () => {
    const text = formatCloverSpendConfirmDescription("image", 30);
    expect(text).not.toMatch(/\d+\s*(분|시간)\s*뒤/);
  });

  it("가격을 모르면 숫자를 지어내지 않고 차감 사실만 말한다", () => {
    const text = formatCloverSpendConfirmDescription("chat", undefined);
    expect(text).not.toMatch(/\d/);
    expect(text).toContain("차감");
    expect(text).not.toContain("자정");
  });
});
