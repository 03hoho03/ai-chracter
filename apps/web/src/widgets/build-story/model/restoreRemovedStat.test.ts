import { describe, expect, it } from "vitest";

import type { StatDefValues } from "@/features/build-story";

import {
  endingsToRestorePriority,
  orderWithPendingRemovals,
  restoreRemovedStat,
  type RemovedStat,
} from "./restoreRemovedStat";

function stat(id: string): StatDefValues {
  return {
    id,
    name: id,
    icon: "Heart",
    color: "color",
    min: 0,
    max: 100,
    initial: 0,
    description: "d",
    perTurnDelta: null,
    changeDirection: "both",
    maxChangePerTurn: null,
  };
}

const A = stat("a");
const B = stat("b");
const C = stat("c");
const D = stat("d");

function ids(stats: readonly StatDefValues[] | undefined): string[] {
  return (stats ?? []).map((each) => each.id);
}

/** 스탯 탭이 하는 대로 시작설정 하나에서 지우기·되돌리기를 차례로 돌린다(되돌릴 수 있는 삭제를 지운 차례대로 쥔다). */
function simulate(initial: StatDefValues[]) {
  let stats = initial;
  const pending: RemovedStat[] = [];
  return {
    remove(id: string): RemovedStat {
      const target = stats.find((each) => each.id === id);
      if (target === undefined) throw new Error(`no stat ${id}`);
      const removed: RemovedStat = {
        startingSetupId: "s1",
        order: orderWithPendingRemovals(ids(stats), pending),
        stat: target,
        priorityEndingIds: [],
      };
      stats = stats.filter((each) => each.id !== id);
      pending.push(removed);
      return removed;
    },
    undo(removed: RemovedStat) {
      const restored = restoreRemovedStat([{ id: "s1", stats }], removed);
      if (restored === undefined) throw new Error("not restored");
      stats = restored.stats;
      pending.splice(pending.indexOf(removed), 1);
    },
    add(next: StatDefValues) {
      stats = [...stats, next];
    },
    ids: () => ids(stats),
  };
}

describe("restoreRemovedStat", () => {
  it("지운 자리에 같은 값(같은 id)으로 다시 넣는다", () => {
    const result = restoreRemovedStat([{ id: "s1", stats: [A, C] }], {
      startingSetupId: "s1",
      order: ["a", "b", "c"],
      stat: B,
    });
    expect(result).toEqual({ startingSetupIndex: 0, stats: [A, B, C] });
  });

  it("맨 앞이었으면 맨 앞에 넣는다", () => {
    const result = restoreRemovedStat([{ id: "s1", stats: [B] }], { startingSetupId: "s1", order: ["a", "b"], stat: A });
    expect(ids(result?.stats)).toEqual(["a", "b"]);
  });

  it("시작설정은 인덱스가 아니라 id 로 찾는다(그 사이 순서가 바뀌어도 원래 시작설정으로)", () => {
    const result = restoreRemovedStat(
      [
        { id: "s2", stats: [] },
        { id: "s1", stats: [A] },
      ],
      { startingSetupId: "s1", order: ["b", "a"], stat: B },
    );
    expect(result).toEqual({ startingSetupIndex: 1, stats: [B, A] });
  });

  it("바로 앞 스탯도 그 사이 지워졌으면 그보다 앞에 남은 스탯 뒤에 넣는다", () => {
    const result = restoreRemovedStat([{ id: "s1", stats: [A, D] }], {
      startingSetupId: "s1",
      order: ["a", "b", "c", "d"],
      stat: C,
    });
    expect(ids(result?.stats)).toEqual(["a", "c", "d"]);
  });

  it("그 사이 새로 추가한 스탯은 제자리에 둔다", () => {
    const run = simulate([A, B]);
    const removedB = run.remove("b");
    run.add(C);
    run.undo(removedB);
    expect(run.ids()).toEqual(["a", "b", "c"]);
  });

  it("시작설정이 사라졌으면 되돌리지 않는다", () => {
    expect(
      restoreRemovedStat([{ id: "s2", stats: [A] }], { startingSetupId: "s1", order: ["b"], stat: B }),
    ).toBeUndefined();
  });

  it("같은 id 의 스탯이 어느 시작설정에든 이미 있으면 되돌리지 않는다(두 번 되돌리기)", () => {
    expect(
      restoreRemovedStat(
        [
          { id: "s1", stats: [A] },
          { id: "s2", stats: [B] },
        ],
        { startingSetupId: "s1", order: ["a", "b"], stat: B },
      ),
    ).toBeUndefined();
  });
});

describe("연달아 지운 스탯을 되돌리는 차례", () => {
  // 이웃한 둘을 앞→뒤, 뒤→앞 두 차례로 지우고, 각각 최근 것부터·오래된 것부터 되돌린다. 넷 다 원래 순서로 돌아와야 한다.
  it.each([
    ["앞→뒤로 지우고 최근 것부터", ["b", "c"], "latest-first"],
    ["앞→뒤로 지우고 오래된 것부터", ["b", "c"], "oldest-first"],
    ["뒤→앞으로 지우고 최근 것부터", ["c", "b"], "latest-first"],
    ["뒤→앞으로 지우고 오래된 것부터", ["c", "b"], "oldest-first"],
  ] as const)("%s 되돌려도 원래 순서다", (_, removeOrder, undoOrder) => {
    const run = simulate([A, B, C, D]);
    const removed = removeOrder.map((id) => run.remove(id));
    expect(run.ids()).toEqual(["a", "d"]);

    for (const each of undoOrder === "latest-first" ? [...removed].reverse() : removed) run.undo(each);

    expect(run.ids()).toEqual(["a", "b", "c", "d"]);
  });

  it("셋을 지우고 가운데 것만 되돌려도 남은 것 사이 제자리에 들어간다", () => {
    const run = simulate([A, B, C, D]);
    run.remove("a");
    const removedB = run.remove("b");
    run.remove("d");

    run.undo(removedB);

    expect(run.ids()).toEqual(["b", "c"]);
  });
});

describe("endingsToRestorePriority", () => {
  it("지울 때 비운 엔딩 가운데 아직 '없음'인 것만 다시 채운다", () => {
    const endings = [
      { id: "e1", priorityStatId: null },
      { id: "e2", priorityStatId: "other" },
      { id: "e3", priorityStatId: null },
      { id: "e4", priorityStatId: null },
    ];
    // e2 는 그 사이 작가가 다른 스탯을 골랐고, e4 는 지울 때 비운 엔딩이 아니다. 지운 엔딩(e9)은 목록에 없어 빠진다.
    expect(endingsToRestorePriority(endings, { priorityEndingIds: ["e1", "e2", "e3", "e9"] })).toEqual([0, 2]);
  });

  it("비운 엔딩이 없으면 아무것도 채우지 않는다", () => {
    expect(endingsToRestorePriority([{ id: "e1", priorityStatId: null }], { priorityEndingIds: [] })).toEqual([]);
  });
});
