import { describe, expect, it } from "vitest";

import { CHAT_MODEL_FEATURE_GATE, isFeatureItemVisible, visibleMoreItems } from "./visibleMoreItems";

const ITEMS = [
  { key: "play-guide", isActive: true },
  { key: "novel", isActive: true, requiredFeature: "novelize" as const },
  { key: "coming-soon", isActive: false },
];

describe("visibleMoreItems", () => {
  it("허용 기능이 없으면 그 기능에 딸린 항목만 빠진다", () => {
    expect(visibleMoreItems(ITEMS, []).map((item) => item.key)).toEqual(["play-guide", "coming-soon"]);
  });

  it("허용 기능이 있으면 전부 남고 순서도 그대로다", () => {
    expect(visibleMoreItems(ITEMS, ["novelize"]).map((item) => item.key)).toEqual(["play-guide", "novel", "coming-soon"]);
  });

  it("준비 중(isActive: false) 항목은 숨기지 않는다", () => {
    expect(visibleMoreItems(ITEMS, []).some((item) => !item.isActive)).toBe(true);
  });

  // 채팅 상위 모델과 소설화는 따로 허용된다 — 한쪽 허용이 다른 쪽 항목을 열면 안 된다.
  it("기능마다 따로 거른다 — 소설화 허용만 있으면 모델 항목은 빠진다", () => {
    const items = [...ITEMS, { key: "chat-model", isActive: true, requiredFeature: "chat_premium_models" as const }];

    expect(visibleMoreItems(items, ["novelize"]).map((item) => item.key)).toEqual(["play-guide", "novel", "coming-soon"]);
    expect(visibleMoreItems(items, ["chat_premium_models"]).map((item) => item.key)).toEqual([
      "play-guide",
      "coming-soon",
      "chat-model",
    ]);
  });
});

describe("isFeatureItemVisible", () => {
  it("요구 기능이 없는 항목은 허용 기능이 없어도 보인다", () => {
    expect(isFeatureItemVisible({}, [])).toBe(true);
  });

  it("요구 기능이 허용돼 있으면 보인다", () => {
    expect(isFeatureItemVisible(CHAT_MODEL_FEATURE_GATE, ["chat_premium_models"])).toBe(true);
  });

  // 다른 기능의 허용으로는 열리지 않는다 — 소설화만 허용된 계정에 모델 칩이 새면 안 된다.
  it("요구 기능이 허용돼 있지 않으면 숨는다", () => {
    expect(isFeatureItemVisible(CHAT_MODEL_FEATURE_GATE, [])).toBe(false);
    expect(isFeatureItemVisible(CHAT_MODEL_FEATURE_GATE, ["novelize"])).toBe(false);
  });

  it("채팅 모델 게이트는 채팅 상위 모델 기능을 요구한다", () => {
    expect(CHAT_MODEL_FEATURE_GATE.requiredFeature).toBe("chat_premium_models");
  });
});
