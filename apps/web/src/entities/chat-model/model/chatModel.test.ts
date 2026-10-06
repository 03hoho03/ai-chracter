import { describe, expect, it } from "vitest";

import { defaultChatTurnCost, isPremiumChatModel } from "./chatModel";

describe("isPremiumChatModel", () => {
  it("기본 모델만 상위 모델이 아니다", () => {
    expect(isPremiumChatModel("gemini")).toBe(false);
    expect(isPremiumChatModel("sonnet")).toBe(true);
    expect(isPremiumChatModel("opus")).toBe(true);
  });
});

describe("defaultChatTurnCost", () => {
  // 빌더 미리보기는 늘 기본 모델이다 — 목록 순서가 아니라 id 로 고른다(상위 모델이 앞에 와도 그 값을 집지 않게).
  it("목록에서 기본 모델 항목의 가격을 고른다", () => {
    expect(
      defaultChatTurnCost([
        { id: "opus", turnCost: 65 },
        { id: "gemini", turnCost: 10 },
      ]),
    ).toBe(10);
  });

  it("목록이 없으면 undefined 다 — 숫자를 지어내지 않는다", () => {
    expect(defaultChatTurnCost(undefined)).toBeUndefined();
    expect(defaultChatTurnCost([{ id: "sonnet", turnCost: 40 }])).toBeUndefined();
  });
});
