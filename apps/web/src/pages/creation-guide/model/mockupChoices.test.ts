import { describe, expect, it } from "vitest";

import { logicOpChoices } from "./mockupChoices";

describe("logicOpChoices", () => {
  it("원고의 nextOp 에 맞는 관계 칩 하나만 고른다", () => {
    expect(logicOpChoices("or")).toEqual([
      { label: "그리고", isSelected: false },
      { label: "또는", isSelected: true },
    ]);
  });

  it("nextOp 가 없으면 빌더처럼 '그리고'를 고른다", () => {
    expect(logicOpChoices(undefined).find((choice) => choice.isSelected)?.label).toBe("그리고");
    expect(logicOpChoices(null).find((choice) => choice.isSelected)?.label).toBe("그리고");
  });

  it("모르는 관계 값은 원고 오류로 던진다", () => {
    expect(() => logicOpChoices("xor")).toThrow("모르는 규칙 관계");
    expect(() => logicOpChoices(1)).toThrow("모르는 규칙 관계");
  });
});
