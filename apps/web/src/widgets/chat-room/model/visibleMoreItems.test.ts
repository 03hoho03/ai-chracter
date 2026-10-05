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
});
