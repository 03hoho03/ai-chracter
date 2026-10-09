import { describe, expect, it } from "vitest";

import { formatIdentityRequiredMessage } from "./identityRequiredMessage";

describe("formatIdentityRequiredMessage", () => {
  // 숫자는 서버 상수에서 온다 — 한도를 바꾸면 문장도 따라간다.
  it("무료 혜택 문장의 대화 수는 받은 값 그대로다", () => {
    expect(formatIdentityRequiredMessage("free-rewards", 7)).toContain("무료 대화 7턴");
    expect(formatIdentityRequiredMessage("free-rewards", 30)).toContain("무료 대화 30턴");
  });

  it("값을 아직 모르면 숫자를 지어내지 않는다", () => {
    expect(formatIdentityRequiredMessage("free-rewards", undefined)).not.toMatch(/\d/);
  });

  // 구매는 게이트와 무관하게 인증을 건다 — 무료 혜택을 말하면 게이트가 꺼진 동안 거짓이다.
  it("구매 문장은 무료 혜택을 말하지 않는다", () => {
    expect(formatIdentityRequiredMessage("purchase", 30)).not.toContain("무료");
  });
});
