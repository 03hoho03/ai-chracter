import { describe, expect, it } from "vitest";

import { visibleMoreItems } from "./visibleMoreItems";

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
