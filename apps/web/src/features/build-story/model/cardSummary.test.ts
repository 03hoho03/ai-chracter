import { describe, expect, it } from "vitest";

import { endingSummary, keywordNoteSummary, keywordNoteTitle, startingSetupSummary } from "./cardSummary";
import type { RuleListItemValues } from "./schema";

function rule(id: string): Extract<RuleListItemValues, { kind: "rule" }> {
  return { kind: "rule", id, statId: "stat", operator: ">=", value: 1, nextOp: null };
}

describe("startingSetupSummary", () => {
  it("marks the first setup as the default and adds the trimmed first prologue line", () => {
    expect(startingSetupSummary({ prologue: "  비 오는 밤  \n둘째 줄" }, 0)).toBe("기본 · 비 오는 밤");
  });

  it("shows only the prologue line for later setups", () => {
    expect(startingSetupSummary({ prologue: "동아리방" }, 2)).toBe("동아리방");
  });

  it("drops an empty prologue line", () => {
    expect(startingSetupSummary({ prologue: "" }, 0)).toBe("기본");
    expect(startingSetupSummary({ prologue: "\n둘째 줄만" }, 0)).toBe("기본");
    expect(startingSetupSummary({ prologue: "   " }, 1)).toBe("");
  });
});

describe("endingSummary", () => {
  it("joins the turn gate and the rule count", () => {
    expect(endingSummary({ turnGate: 10, statRules: [] })).toBe("10턴 이후 · 규칙 0개");
  });

  it("counts each rule inside a group", () => {
    const statRules: RuleListItemValues[] = [
      rule("a"),
      { kind: "group", id: "g", rules: [rule("b"), rule("c")], nextOp: null },
    ];
    expect(endingSummary({ turnGate: 25, statRules })).toBe("25턴 이후 · 규칙 3개");
  });

  it("counts an empty group as no rules", () => {
    const statRules: RuleListItemValues[] = [rule("a"), { kind: "group", id: "empty", rules: [], nextOp: null }];
    expect(endingSummary({ turnGate: 25, statRules })).toBe("25턴 이후 · 규칙 1개");
  });

  it("drops the turn gate when it is not a number (an emptied number field)", () => {
    expect(endingSummary({ turnGate: Number.NaN, statRules: [rule("a")] })).toBe("규칙 1개");
  });
});

describe("keywordNoteTitle", () => {
  it("uses the trimmed name", () => {
    expect(keywordNoteTitle({ name: "  유나의 비밀 ", triggerKeywords: ["유나"] })).toBe("유나의 비밀");
  });

  it("falls back to the first trigger keyword when the name is blank", () => {
    expect(keywordNoteTitle({ name: "  ", triggerKeywords: ["상영회", "필름"] })).toBe("상영회");
  });

  it("has no title when both are empty", () => {
    expect(keywordNoteTitle({ name: "", triggerKeywords: [] })).toBeUndefined();
  });
});

describe("keywordNoteSummary", () => {
  it("shows only the always-on mark for always-on notes", () => {
    expect(keywordNoteSummary({ alwaysOn: true, stickyTurns: 3, triggerKeywords: ["a"] })).toEqual({
      text: "상시",
      isAlwaysOn: true,
    });
  });

  it("shows the trigger count without a sticky part when the note lasts only this turn", () => {
    expect(keywordNoteSummary({ alwaysOn: false, stickyTurns: 0, triggerKeywords: ["a", "b"] })).toEqual({
      text: "트리거 2개",
      isAlwaysOn: false,
    });
  });

  it("puts the sticky turns before the trigger count", () => {
    expect(keywordNoteSummary({ alwaysOn: false, stickyTurns: 3, triggerKeywords: [] })).toEqual({
      text: "유지 3턴 · 트리거 0개",
      isAlwaysOn: false,
    });
  });
});
