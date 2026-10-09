import { describe, expect, it } from "vitest";

import { orderWithPendingRemovals, restoreIndex, type RemovalPlace } from "./removalOrder";

/** 반복 항목 탭이 하는 대로 목록 하나에서 지우기·되돌리기를 차례로 돌린다(되돌릴 수 있는 삭제를 지운 차례대로 쥔다). */
function simulate(initial: string[]) {
  let ids = initial;
  const pending: RemovalPlace[] = [];
  return {
    remove(id: string): RemovalPlace {
      if (!ids.includes(id)) throw new Error(`no item ${id}`);
      const removed: RemovalPlace = { id, order: orderWithPendingRemovals(ids, pending) };
      ids = ids.filter((each) => each !== id);
      pending.push(removed);
      return removed;
    },
    undo(removed: RemovalPlace) {
      const index = restoreIndex(ids, removed);
      if (index === undefined) throw new Error("not restored");
      ids = [...ids.slice(0, index), removed.id, ...ids.slice(index)];
      pending.splice(pending.indexOf(removed), 1);
    },
    add(id: string) {
      ids = [...ids, id];
    },
    ids: () => ids,
  };
}

describe("restoreIndex", () => {
  it("지운 자리에 다시 넣는다", () => {
    expect(restoreIndex(["a", "c"], { id: "b", order: ["a", "b", "c"] })).toBe(1);
  });

  it("맨 앞이었으면 맨 앞에 넣는다", () => {
    expect(restoreIndex(["b"], { id: "a", order: ["a", "b"] })).toBe(0);
  });

  it("바로 앞 항목도 그 사이 지워졌으면 그보다 앞에 남은 항목 뒤에 넣는다", () => {
    expect(restoreIndex(["a", "d"], { id: "c", order: ["a", "b", "c", "d"] })).toBe(1);
  });

  it("앞에 있던 항목이 하나도 안 남았으면 맨 앞에 넣는다", () => {
    expect(restoreIndex(["d"], { id: "c", order: ["a", "b", "c", "d"] })).toBe(0);
  });

  it("같은 id 가 이미 있으면 되돌리지 않는다(두 번 되돌리기)", () => {
    expect(restoreIndex(["a", "b"], { id: "b", order: ["a", "b"] })).toBeUndefined();
  });

  it("그 사이 새로 추가한 항목은 제자리에 둔다", () => {
    const run = simulate(["a", "b"]);
    const removedB = run.remove("b");
    run.add("c");
    run.undo(removedB);
    expect(run.ids()).toEqual(["a", "b", "c"]);
  });
});

describe("연달아 지운 항목을 되돌리는 차례", () => {
  // 이웃한 둘을 앞→뒤, 뒤→앞 두 차례로 지우고, 각각 최근 것부터·오래된 것부터 되돌린다. 넷 다 원래 순서로 돌아와야 한다.
  it.each([
    ["앞→뒤로 지우고 최근 것부터", ["b", "c"], "latest-first"],
    ["앞→뒤로 지우고 오래된 것부터", ["b", "c"], "oldest-first"],
    ["뒤→앞으로 지우고 최근 것부터", ["c", "b"], "latest-first"],
    ["뒤→앞으로 지우고 오래된 것부터", ["c", "b"], "oldest-first"],
  ] as const)("%s 되돌려도 원래 순서다", (_, removeOrder, undoOrder) => {
    const run = simulate(["a", "b", "c", "d"]);
    const removed = removeOrder.map((id) => run.remove(id));
    expect(run.ids()).toEqual(["a", "d"]);

    for (const each of undoOrder === "latest-first" ? [...removed].reverse() : removed) run.undo(each);

    expect(run.ids()).toEqual(["a", "b", "c", "d"]);
  });

  it("셋을 지우고 가운데 것만 되돌려도 남은 것 사이 제자리에 들어간다", () => {
    const run = simulate(["a", "b", "c", "d"]);
    run.remove("a");
    const removedB = run.remove("b");
    run.remove("d");

    run.undo(removedB);

    expect(run.ids()).toEqual(["b", "c"]);
  });

  it("되돌린 삭제는 다음 삭제의 순서에 다시 끼우지 않는다", () => {
    expect(orderWithPendingRemovals(["a", "b", "c"], [{ id: "b", order: ["a", "b", "c"] }])).toEqual(["a", "b", "c"]);
  });
});
