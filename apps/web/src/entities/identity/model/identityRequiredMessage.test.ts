import { describe, expect, it } from "vitest";

import { formatIdentityRequiredMessage } from "./identityRequiredMessage";

/** 하루 무료 대화는 없다. 인증하면 받는 것은 매일 출석 클로버와 미션 클로버이고, 출석판 스위치나 무료 대화 수를 읽지
 * 않고도 그 문장이어야 한다 — 읽던 값이 응답에서 빠져도 없는 무료 대화를 약속하지 않게. */
describe("formatIdentityRequiredMessage", () => {
  it("무료 혜택 자리는 출석 클로버와 미션 클로버를 말한다", () => {
    expect(formatIdentityRequiredMessage("free-rewards")).toBe(
      "본인인증을 하면 매일 출석 클로버와 미션 클로버를 받을 수 있어요.",
    );
  });

  it.each(["free-rewards", "purchase", "attendance"] as const)("%s 자리는 무료 대화를 말하지 않는다", (reason) => {
    const message = formatIdentityRequiredMessage(reason);
    expect(message).not.toContain("무료 대화");
    expect(message).not.toMatch(/\d+턴/);
  });

  // 구매는 게이트와 무관하게 인증을 건다 — 무료 혜택을 말하면 게이트가 꺼진 동안 거짓이다.
  it("구매 문장은 무료 혜택을 말하지 않는다", () => {
    expect(formatIdentityRequiredMessage("purchase")).not.toContain("무료");
  });

  it("출석판 자리의 문장은 출석 보상에 인증이 필요하다고 말한다", () => {
    expect(formatIdentityRequiredMessage("attendance")).toBe("출석 보상을 받으려면 본인인증이 필요해요.");
  });
});
