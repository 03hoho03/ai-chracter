import { describe, expect, it } from "vitest";

import {
  endingSummary,
  keywordNoteSummary,
  keywordNoteTitle,
  situationNoteConditionSummary,
  situationNoteTitle,
  startingSetupSummary,
} from "./cardSummary";
import type { RuleListItemValues, SingleRuleValues, StatDefValues } from "./schema";

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

const STAT: StatDefValues = {
  id: "days",
  name: "상영회까지",
  icon: "Heart",
  color: "c",
  min: 0,
  max: 42,
  initial: 42,
  description: "d",
  perTurnDelta: null,
  changeDirection: "both",
  maxChangePerTurn: null,
};

function noteRule(id: string, statId = "days", value = 0): SingleRuleValues {
  return { kind: "rule", id, statId, operator: "<=", value, nextOp: null };
}

describe("situationNoteConditionSummary", () => {
  it("조건 하나는 조건 줄의 글자 그대로 보인다", () => {
    expect(situationNoteConditionSummary([noteRule("r1")], [STAT])).toBe("상영회까지 <= 0");
  });

  it("조건이 더 있으면 첫 조건 뒤에 나머지 개수를 붙인다(그룹 안 조건도 센다)", () => {
    const items: RuleListItemValues[] = [
      noteRule("r1", "days", 7),
      { kind: "group", id: "g1", nextOp: null, rules: [noteRule("r2"), noteRule("r3")] },
    ];

    expect(situationNoteConditionSummary(items, [STAT])).toBe("상영회까지 <= 7 외 2개");
  });

  it("첫 항목이 그룹이면 전체 개수만 보인다", () => {
    const items: RuleListItemValues[] = [{ kind: "group", id: "g1", nextOp: null, rules: [noteRule("r1"), noteRule("r2")] }];

    expect(situationNoteConditionSummary(items, [STAT])).toBe("조건 2개");
  });

  it("조건이 없으면(빈 그룹만 있어도) '조건 없음'이다", () => {
    expect(situationNoteConditionSummary([], [STAT])).toBe("조건 없음");
    expect(situationNoteConditionSummary([{ kind: "group", id: "g1", nextOp: null, rules: [] }], [STAT])).toBe(
      "조건 없음",
    );
  });

  // 조건 줄이 스탯 칸에 그리는 이름과 같아야 접힌 머리 줄만 보고도 그 노트를 열어 고칠 줄을 찾는다.
  it("지워진 스탯을 가리키는 첫 조건은 '지워진 스탯'으로 부른다", () => {
    expect(situationNoteConditionSummary([noteRule("r1", "gone")], [STAT])).toBe("지워진 스탯 <= 0");
  });
});

describe("situationNoteTitle", () => {
  it("uses the trimmed name, or the first line of the situation when the name is blank", () => {
    expect(situationNoteTitle({ name: "  상영회 당일 ", content: "오늘은" })).toBe("상영회 당일");
    expect(situationNoteTitle({ name: "", content: "오늘은 상영회 당일이다.\n둘째 줄" })).toBe("오늘은 상영회 당일이다.");
  });
});
