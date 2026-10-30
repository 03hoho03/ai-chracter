import { describe, expect, it } from "vitest";

import { chatModelBadges, formatChatModelPrice, formatPremiumModelConfirm, formatPremiumModelShortage } from "./chatModelCopy";

const GEMINI = { id: "gemini", name: "Gemini", isDefault: true, beta: false, turnCost: 10 } as const;
const OPUS = { id: "opus", name: "Claude Opus 5.5", isDefault: false, beta: true, turnCost: 120 } as const;

/** 하루 무료 대화는 없다 — 기본·상위 모두 첫 턴부터 깎이므로 "무료 대화" 는 둘을 가르는 정보가 아니라 가격만 말한다.
 * 출석판 스위치나 본인인증 게이트 여부를 읽지 않고도 그 문장이어야 한다. */
describe("formatChatModelPrice", () => {
  it("두 모델 모두 턴 가격만 말한다", () => {
    expect(formatChatModelPrice(GEMINI)).toBe("턴마다 클로버 10개");
    expect(formatChatModelPrice(OPUS)).toBe("턴마다 클로버 120개");
  });

  it("무료 대화를 말하지 않는다", () => {
    expect(formatChatModelPrice(GEMINI)).not.toContain("무료");
    expect(formatChatModelPrice(OPUS)).not.toContain("무료");
  });
});

describe("formatPremiumModelConfirm", () => {
  it("턴 가격과 따로 묻지 않는다는 것을 말하고 무료 대화는 말하지 않는다", () => {
    const text = formatPremiumModelConfirm(OPUS);
    expect(text).toBe("첫 턴부터 턴마다 클로버 120개를 써요. 바꾸면 다음 턴부터 따로 묻지 않고 바로 차감돼요.");
    expect(text).not.toContain("무료");
  });
});

describe("formatPremiumModelShortage", () => {
  // 가격은 서버 값이다 — 숫자를 문구에 고정하면 다음 가격 변경에서 화면과 서버가 갈린다.
  it.each([120, 77])("턴 가격 %d 를 그대로 담는다", (turnCost) => {
    const text = formatPremiumModelShortage({ ...OPUS, turnCost });
    expect(text).toContain(`턴마다 클로버 ${turnCost}개`);
    expect(text).toContain("클로버가 부족해요");
  });

  // 정산 시간 초과·확인 실패 때 클로버가 남을 수 있어 돌려준다고 약속하지 않는다.
  it("환불을 약속하지 않는다", () => {
    expect(formatPremiumModelShortage(OPUS)).not.toMatch(/환불|돌려/);
  });
});

describe("chatModelBadges", () => {
  it("베타이고 지금 쓰는 모델이면 이름 다음에 베타, 사용 중 순서다", () => {
    expect(chatModelBadges(OPUS, "opus")).toEqual(["베타", "사용 중"]);
  });

  it("베타가 아니면 베타 배지가 없다", () => {
    expect(chatModelBadges(GEMINI, "gemini")).toEqual(["사용 중"]);
    expect(chatModelBadges(GEMINI, "opus")).toEqual([]);
  });

  // 베타는 서버의 `beta` 로만 정한다 — id 로 정하면 상위 모델이 정식이 되는 날 화면을 따로 고쳐야 한다.
  it("상위 모델이어도 beta 가 거짓이거나 없으면 베타 배지가 없다", () => {
    expect(chatModelBadges({ ...OPUS, beta: false }, "gemini")).toEqual([]);
    expect(chatModelBadges({ id: OPUS.id }, "gemini")).toEqual([]);
  });

  it("기본 모델이어도 beta 가 참이면 베타 배지를 단다", () => {
    expect(chatModelBadges({ ...GEMINI, beta: true }, "opus")).toEqual(["베타"]);
  });
});
