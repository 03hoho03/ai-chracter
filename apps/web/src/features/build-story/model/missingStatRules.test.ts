import { describe, expect, it } from "vitest";

import { hasRuleWithMissingStat, isMissingStat } from "./missingStatRules";
import type { RuleListItemValues, SingleRuleValues } from "./schema";

function rule(id: string, statId: string): SingleRuleValues {
  return { kind: "rule", id, statId, operator: ">=", value: 0, nextOp: null };
}

const stats = [{ id: "kept" }];

describe("isMissingStat", () => {
  it("같은 시작설정의 스탯 목록에 없는 스탯이면 참", () => {
    expect(isMissingStat("gone", stats)).toBe(true);
    expect(isMissingStat("kept", stats)).toBe(false);
    expect(isMissingStat("kept", [])).toBe(true);
  });
});

describe("hasRuleWithMissingStat", () => {
  it("최상위 조건이나 그룹 안 조건 하나라도 지워진 스탯을 가리키면 참", () => {
    const topLevel: RuleListItemValues[] = [rule("r1", "kept"), rule("r2", "gone")];
    const inGroup: RuleListItemValues[] = [{ kind: "group", id: "g1", nextOp: null, rules: [rule("r3", "gone")] }];

    expect(hasRuleWithMissingStat(topLevel, stats)).toBe(true);
    expect(hasRuleWithMissingStat(inGroup, stats)).toBe(true);
  });

  it("모든 조건이 있는 스탯을 가리키거나 조건이 없으면 거짓", () => {
    const items: RuleListItemValues[] = [
      rule("r1", "kept"),
      { kind: "group", id: "g1", nextOp: null, rules: [rule("r2", "kept")] },
      { kind: "group", id: "g2", nextOp: null, rules: [] },
    ];

    expect(hasRuleWithMissingStat(items, stats)).toBe(false);
    expect(hasRuleWithMissingStat([], stats)).toBe(false);
  });
});
