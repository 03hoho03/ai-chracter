import { describe, expect, it } from "vitest";

import { evaluateRuleList, type RuleListItem, type SingleRule } from "./ending-rules";

function rule(overrides: Partial<SingleRule> & Pick<SingleRule, "statId" | "operator" | "value">): SingleRule {
  return { kind: "rule", id: overrides.statId, nextOp: null, ...overrides };
}

describe("evaluateRuleList", () => {
  it("returns true for an empty list (judgePrompt만으로 판정)", () => {
    expect(evaluateRuleList([], {})).toBe(true);
  });

  it("evaluates a single rule", () => {
    expect(evaluateRuleList([rule({ statId: "affection", operator: ">=", value: 50 })], { affection: 60 })).toBe(
      true,
    );
    expect(evaluateRuleList([rule({ statId: "affection", operator: ">=", value: 50 })], { affection: 40 })).toBe(
      false,
    );
  });

  it("accumulates left-to-right with mixed and/or (no operator precedence)", () => {
    // true and false or true => (true and false) or true => true
    const items: RuleListItem[] = [
      rule({ statId: "a", operator: "==", value: 1, nextOp: "and" }),
      rule({ statId: "b", operator: "==", value: 1, nextOp: "or" }),
      rule({ statId: "c", operator: "==", value: 1, nextOp: null }),
    ];
    expect(evaluateRuleList(items, { a: 1, b: 0, c: 1 })).toBe(true);

    // true or false and false => (true or false) and false => false
    const items2: RuleListItem[] = [
      rule({ statId: "a", operator: "==", value: 1, nextOp: "or" }),
      rule({ statId: "b", operator: "==", value: 1, nextOp: "and" }),
      rule({ statId: "c", operator: "==", value: 1, nextOp: null }),
    ];
    expect(evaluateRuleList(items2, { a: 1, b: 0, c: 0 })).toBe(false);
  });

  it("recurses into groups using the same accumulation algorithm", () => {
    // top-level: group(true) and singleRule(false) => false
    const items: RuleListItem[] = [
      {
        kind: "group",
        id: "g1",
        nextOp: "and",
        rules: [
          rule({ statId: "a", operator: ">", value: 0, nextOp: "or" }),
          rule({ statId: "b", operator: ">", value: 0, nextOp: null }),
        ],
      },
      rule({ statId: "c", operator: "==", value: 1, nextOp: null }),
    ];
    // group: a>0 (false) or b>0 (true) => true; top: true and c==1(false) => false
    expect(evaluateRuleList(items, { a: 0, b: 1, c: 0 })).toBe(false);

    // group: a>0(false) or b>0(false) => false; top: false and ... short-circuits to false regardless of c
    expect(evaluateRuleList(items, { a: 0, b: 0, c: 1 })).toBe(false);

    // group: a>0(true) or b>0(false) => true; top: true and c==1(true) => true
    expect(evaluateRuleList(items, { a: 1, b: 0, c: 1 })).toBe(true);
  });
});
