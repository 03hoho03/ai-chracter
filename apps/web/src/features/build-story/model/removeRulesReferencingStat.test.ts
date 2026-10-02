import { describe, expect, it, vi } from "vitest";

import { planStatRemoval, removeRulesReferencingStat } from "./removeRulesReferencingStat";
import type { RuleListItemValues, SingleRuleValues } from "./schema";

function rule(id: string, statId: string, nextOp: SingleRuleValues["nextOp"] = null): SingleRuleValues {
  return { kind: "rule", id, statId, operator: ">=", value: 50, nextOp };
}

describe("removeRulesReferencingStat", () => {
  it("removes top-level rules that point at the removed stat and keeps the rest in order", () => {
    const items: RuleListItemValues[] = [rule("r1", "gone", "and"), rule("r2", "kept", "or"), rule("r3", "gone")];

    expect(removeRulesReferencingStat(items, "gone")).toEqual([rule("r2", "kept", "or")]);
  });

  it("removes matching rules inside a group and keeps the group while other rules remain", () => {
    const items: RuleListItemValues[] = [
      { kind: "group", id: "g1", nextOp: "and", rules: [rule("r1", "gone", "or"), rule("r2", "kept")] },
    ];

    expect(removeRulesReferencingStat(items, "gone")).toEqual([
      { kind: "group", id: "g1", nextOp: "and", rules: [rule("r2", "kept")] },
    ]);
  });

  it("drops a group whose every rule pointed at the removed stat", () => {
    // 빈 그룹은 참으로 평가된다 — 남겨 두면 `(지운 스탯 조건) or 다른 조건` 이 언제나 참이 된다.
    const items: RuleListItemValues[] = [
      { kind: "group", id: "g1", nextOp: "or", rules: [rule("r1", "gone", "and"), rule("r2", "gone")] },
      rule("r3", "kept"),
    ];

    expect(removeRulesReferencingStat(items, "gone")).toEqual([rule("r3", "kept")]);
  });

  it("leaves a group the author left empty untouched", () => {
    const items: RuleListItemValues[] = [{ kind: "group", id: "g1", nextOp: null, rules: [] }];

    expect(removeRulesReferencingStat(items, "gone")).toEqual(items);
  });

  it("returns the same list when nothing points at the removed stat, so the caller can skip the write", () => {
    const items: RuleListItemValues[] = [
      rule("r1", "kept", "and"),
      { kind: "group", id: "g1", nextOp: null, rules: [rule("r2", "other")] },
    ];

    expect(removeRulesReferencingStat(items, "gone")).toBe(items);
  });
});

describe("planStatRemoval", () => {
  const confirmed = () => vi.fn((_ruleCount: number) => Promise.resolve(true));

  it("asks first with the number of conditions that go with the stat, counting rules inside groups", async () => {
    const confirm = confirmed();
    const group: RuleListItemValues = {
      kind: "group",
      id: "g1",
      nextOp: null,
      rules: [rule("r3", "gone", "or"), rule("r4", "gone")],
    };
    const endings = [{ statRules: [rule("r1", "gone", "and"), rule("r2", "kept")] }, { statRules: [group] }];

    const updates = await planStatRemoval(endings, "gone", confirm);

    expect(confirm).toHaveBeenCalledExactlyOnceWith(3);
    expect(updates).toEqual([
      { endingIndex: 0, statRules: [rule("r2", "kept")] },
      { endingIndex: 1, statRules: [] },
    ]);
  });

  it("changes nothing when the author cancels", async () => {
    const endings = [{ statRules: [rule("r1", "gone")] }];
    const cancelled = vi.fn(() => Promise.resolve(false));

    expect(await planStatRemoval(endings, "gone", cancelled)).toBeUndefined();
  });

  it("removes without asking when no condition uses the stat", async () => {
    const confirm = confirmed();
    const endings = [{ statRules: [rule("r1", "kept")] }, { statRules: [] }];

    expect(await planStatRemoval(endings, "gone", confirm)).toEqual([]);
    expect(confirm).not.toHaveBeenCalled();
  });
});
