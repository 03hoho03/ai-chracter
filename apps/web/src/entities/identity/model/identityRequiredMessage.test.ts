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

/** 출석판이 켜지면 하루 무료 대화가 없어진다(서버가 무료 대화 수를 0 으로 보낸다). 꺼진 동안의 문장은 그대로다. */
describe("formatIdentityRequiredMessage — 출석판", () => {
  it.each([0, undefined])("켜져 있으면 무료 대화 대신 출석 클로버를 말한다(무료 대화 수 %s)", (turns) => {
    const message = formatIdentityRequiredMessage("free-rewards", turns, true);
    expect(message).toBe("본인인증을 하면 매일 출석 클로버와 미션 클로버를 받을 수 있어요.");
    expect(message).not.toContain("0턴");
    expect(message).not.toContain("무료 대화");
  });

  // 켜졌는데 가격 응답이 늦어 꺼짐 문장이 나가는 순간에도 없는 무료 대화를 약속하지 않는다.
  it("꺼져 있어도 무료 대화 수가 0 이면 무료 대화를 말하지 않는다", () => {
    const message = formatIdentityRequiredMessage("free-rewards", 0, false);
    expect(message).toBe("본인인증을 하면 미션 클로버를 받을 수 있어요.");
    expect(message).not.toContain("0턴");
  });

  it("꺼져 있고 무료 대화가 있으면 지금 문장 그대로다", () => {
    expect(formatIdentityRequiredMessage("free-rewards", 15, false)).toBe(
      "본인인증을 하면 매일 무료 대화 15턴과 미션 클로버를 받을 수 있어요.",
    );
    expect(formatIdentityRequiredMessage("free-rewards", undefined, false)).toBe(
      "본인인증을 하면 매일 무료 대화와 미션 클로버를 받을 수 있어요.",
    );
  });

  it("출석판 자리의 문장은 출석 보상에 인증이 필요하다고 말한다", () => {
    expect(formatIdentityRequiredMessage("attendance", 0, true)).toBe("출석 보상을 받으려면 본인인증이 필요해요.");
  });

  it("구매 문장은 출석판과 무관하다", () => {
    expect(formatIdentityRequiredMessage("purchase", 0, true)).toBe(formatIdentityRequiredMessage("purchase", 15, false));
  });
});
