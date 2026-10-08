import { describe, expect, it } from "vitest";

import { canSaveBoardLayout } from "./boardLayoutSaveGate";

describe("canSaveBoardLayout", () => {
  it("배치와 인물을 다 받았으면 저장한다", () => {
    expect(canSaveBoardLayout({ isLayoutFailed: false, hasCharacters: true })).toBe(true);
  });

  it("배치를 받지 못해 자동 배치로 보이는 동안은 저장하지 않는다(옮겨 둔 자리를 덮는다)", () => {
    expect(canSaveBoardLayout({ isLayoutFailed: true, hasCharacters: true })).toBe(false);
  });

  it("인물 목록이 아직 없으면 저장하지 않는다(인물 카드 자리가 빠진다)", () => {
    expect(canSaveBoardLayout({ isLayoutFailed: false, hasCharacters: false })).toBe(false);
  });
});
