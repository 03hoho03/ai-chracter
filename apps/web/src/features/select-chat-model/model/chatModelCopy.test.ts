import { describe, expect, it } from "vitest";

import { formatChatModelPrice, formatPremiumModelConfirm } from "./chatModelCopy";

const GEMINI = { id: "gemini", name: "Gemini", beta: false, turnCost: 10 } as const;
const OPUS = { id: "opus", name: "Claude Opus 5.5", beta: true, turnCost: 120 } as const;

describe("formatChatModelPrice", () => {
  it("상위 모델은 턴 가격과 무료 대화가 없다는 사실을 함께 말한다", () => {
    const text = formatChatModelPrice(OPUS, false);
    expect(text).toContain("120개");
    expect(text).toContain("무료 대화 없음");
  });

  // 짝: 기본 모델에 "무료 대화 없음"이 붙으면 거짓이다 — 하루 무료 대화를 다 쓴 뒤에만 깎인다.
  it("기본 모델은 무료 대화 뒤부터 깎인다고 말한다", () => {
    const text = formatChatModelPrice(GEMINI, false);
    expect(text).toContain("10개");
    expect(text).toContain("무료 대화를 다 쓴 뒤");
    expect(text).not.toContain("무료 대화 없음");
  });

  // 본인인증 게이트에 걸린 회원은 기본 모델도 무료 대화가 없다 — "다 쓴 뒤"는 그 회원에게 거짓이다.
  it("게이트에 걸린 회원에게 기본 모델은 무료 대화 없이 깎인다고 말한다", () => {
    const text = formatChatModelPrice(GEMINI, true);
    expect(text).toContain("10개");
    expect(text).not.toContain("다 쓴 뒤");
    expect(text).toContain("본인인증");
  });
});

describe("formatPremiumModelConfirm", () => {
  it("턴 가격, 무료 대화 없음, 따로 묻지 않는다는 것을 모두 말한다", () => {
    const text = formatPremiumModelConfirm(OPUS);
    expect(text).toContain("120개");
    expect(text).toContain("무료 대화 없이");
    expect(text).toContain("따로 묻지 않고");
  });
});
