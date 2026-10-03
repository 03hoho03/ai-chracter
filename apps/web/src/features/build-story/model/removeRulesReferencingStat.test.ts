import { describe, expect, it, vi } from "vitest";

import {
  countRules,
  planStatRemoval,
  removeRuleListItem,
  removeRulesReferencingStat,
  type StatRemovalCounts,
} from "./removeRulesReferencingStat";
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

describe("removeRulesReferencingStat matches deleting the same conditions by hand", () => {
  // 엔딩 탭에서 작가가 조건 줄의 삭제 버튼을 하나씩 누른 결과. 그룹 안 조건은 그 그룹의 목록에서 지우고, 그래서 그룹이 비면
  // 그룹 삭제 버튼까지 누른다(스탯 삭제가 빈 그룹을 그룹째 지우는 것과 같은 결과를 얻는 수동 동작).
  function removeByHand(items: RuleListItemValues[], statId: string): RuleListItemValues[] {
    let next = items;
    for (const item of items) {
      if (item.kind === "rule") {
        if (item.statId === statId) next = removeRuleListItem(next, item.id);
        continue;
      }
      let groupRules: RuleListItemValues[] = item.rules;
      for (const groupRule of item.rules) {
        if (groupRule.statId === statId) groupRules = removeRuleListItem(groupRules, groupRule.id);
      }
      if (groupRules === item.rules) continue;
      next =
        groupRules.length === 0
          ? removeRuleListItem(next, item.id)
          : next.map((current) =>
              current.id === item.id
                ? { ...item, rules: groupRules.filter((rule): rule is SingleRuleValues => rule.kind === "rule") }
                : current,
            );
    }
    return next;
  }

  it.each<[string, RuleListItemValues[]]>([
    ["A 또는 X 그리고 B", [rule("a", "kept", "or"), rule("x", "gone", "and"), rule("b", "kept")]],
    ["A 그리고 X 또는 B", [rule("a", "kept", "and"), rule("x", "gone", "or"), rule("b", "kept")]],
    ["맨 앞 X", [rule("x", "gone", "or"), rule("a", "kept", "and"), rule("b", "kept")]],
    ["맨 뒤 X", [rule("a", "kept", "or"), rule("x", "gone", null)]],
    [
      "그룹 안의 X 와 비게 되는 그룹",
      [
        {
          kind: "group",
          id: "g1",
          nextOp: "or",
          rules: [rule("a", "kept", "or"), rule("x", "gone", "and"), rule("b", "kept")],
        },
        { kind: "group", id: "g2", nextOp: "and", rules: [rule("y", "gone")] },
        rule("c", "kept"),
      ],
    ],
  ])("keeps the same and/or links as manual deletion: %s", (_label, items) => {
    expect(removeRulesReferencingStat(items, "gone")).toEqual(removeByHand(items, "gone"));
  });
});

describe("planStatRemoval", () => {
  const confirmed = () => vi.fn((_counts: StatRemovalCounts) => Promise.resolve(true));
  const noNotes: { conditionRules: RuleListItemValues[] }[] = [];

  it("asks first with the number of ending conditions that go with the stat, counting rules inside groups", async () => {
    const confirm = confirmed();
    const group: RuleListItemValues = {
      kind: "group",
      id: "g1",
      nextOp: null,
      rules: [rule("r3", "gone", "or"), rule("r4", "gone")],
    };
    const endings = [{ statRules: [rule("r1", "gone", "and"), rule("r2", "kept")] }, { statRules: [group] }];

    const updates = await planStatRemoval({ endings, situationNotes: noNotes }, "gone", confirm);

    expect(confirm).toHaveBeenCalledExactlyOnceWith({ endingRuleCount: 3, noteRuleCount: 0, emptiedNoteCount: 0 });
    expect(updates).toEqual({
      endings: [
        { endingIndex: 0, statRules: [rule("r2", "kept")] },
        { endingIndex: 1, statRules: [] },
      ],
      situationNotes: [],
    });
  });

  it("counts ending and situation note conditions together and asks only once", async () => {
    const confirm = confirmed();
    const endings = [{ statRules: [rule("e1", "gone")] }];
    const situationNotes = [
      { conditionRules: [rule("n1", "gone", "and"), rule("n2", "kept")] },
      { conditionRules: [{ kind: "group", id: "g1", nextOp: null, rules: [rule("n3", "gone"), rule("n4", "gone")] }] },
      { conditionRules: [rule("n5", "kept")] },
    ] satisfies { conditionRules: RuleListItemValues[] }[];

    const updates = await planStatRemoval({ endings, situationNotes }, "gone", confirm);

    // 두 번째 노트는 조건이 하나도 남지 않는다 — 발행이 막히는 노트라 확인 문장이 따로 알린다.
    expect(confirm).toHaveBeenCalledExactlyOnceWith({ endingRuleCount: 1, noteRuleCount: 3, emptiedNoteCount: 1 });
    expect(updates).toEqual({
      endings: [{ endingIndex: 0, statRules: [] }],
      situationNotes: [
        { noteIndex: 0, conditionRules: [rule("n2", "kept")] },
        { noteIndex: 1, conditionRules: [] },
      ],
    });
  });

  it("asks when only situation note conditions use the stat", async () => {
    const confirm = confirmed();
    const situationNotes = [{ conditionRules: [rule("n1", "gone")] }];

    const updates = await planStatRemoval({ endings: [], situationNotes }, "gone", confirm);

    expect(confirm).toHaveBeenCalledExactlyOnceWith({ endingRuleCount: 0, noteRuleCount: 1, emptiedNoteCount: 1 });
    expect(updates).toEqual({ endings: [], situationNotes: [{ noteIndex: 0, conditionRules: [] }] });
  });

  it("does not count a note the author had already left without conditions as emptied by this removal", async () => {
    const confirm = confirmed();
    const situationNotes = [
      { conditionRules: [] },
      { conditionRules: [rule("n1", "gone"), rule("n2", "kept")] },
    ] satisfies { conditionRules: RuleListItemValues[] }[];

    await planStatRemoval({ endings: [], situationNotes }, "gone", confirm);

    expect(confirm).toHaveBeenCalledExactlyOnceWith({ endingRuleCount: 0, noteRuleCount: 1, emptiedNoteCount: 0 });
  });

  it("changes nothing when the author cancels", async () => {
    const endings = [{ statRules: [rule("r1", "gone")] }];
    const situationNotes = [{ conditionRules: [rule("n1", "gone")] }];
    const cancelled = vi.fn(() => Promise.resolve(false));

    expect(await planStatRemoval({ endings, situationNotes }, "gone", cancelled)).toBeUndefined();
  });

  it("removes without asking when no condition uses the stat", async () => {
    const confirm = confirmed();
    const endings = [{ statRules: [rule("r1", "kept")] }, { statRules: [] }];
    const situationNotes = [{ conditionRules: [rule("n1", "kept")] }];

    expect(await planStatRemoval({ endings, situationNotes }, "gone", confirm)).toEqual({
      endings: [],
      situationNotes: [],
    });
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("countRules", () => {
  it("counts rules inside groups and not the groups themselves", () => {
    const items: RuleListItemValues[] = [
      rule("r1", "a"),
      { kind: "group", id: "g1", nextOp: null, rules: [rule("r2", "a"), rule("r3", "b")] },
      { kind: "group", id: "g2", nextOp: null, rules: [] },
    ];

    expect(countRules(items)).toBe(3);
  });
});
