import { describe, expect, it } from "vitest";

import { dragMoveIndices, nextAnnouncement, orderAfterMove, stepMove } from "./listMove";

describe("dragMoveIndices", () => {
  const ids = ["a", "b", "c"];

  it("moves the dragged item to the position of the item it was dropped on", () => {
    expect(dragMoveIndices(ids, "c", "a")).toEqual({ from: 2, to: 0 });
    expect(dragMoveIndices(ids, "a", "b")).toEqual({ from: 0, to: 1 });
  });

  it("does nothing when dropped on itself, outside the list, or with an unknown id", () => {
    expect(dragMoveIndices(ids, "b", "b")).toBeUndefined();
    expect(dragMoveIndices(ids, "b", null)).toBeUndefined();
    expect(dragMoveIndices(ids, "x", "a")).toBeUndefined();
    expect(dragMoveIndices(ids, "a", "x")).toBeUndefined();
  });
});

/** 화면처럼 포커스가 있는 항목의 지금 자리에서 화살표를 누르고, 목록과 포커스를 이동 뒤 상태로 돌려준다. */
function press(state: { ids: string[]; focused: string }, step: -1 | 1) {
  const result = stepMove(state.ids, state.ids.indexOf(state.focused), step);
  if (!result) return state;
  const ids = [...state.ids];
  const [moved] = ids.splice(result.from, 1);
  if (moved !== undefined) ids.splice(result.to, 0, moved);
  return { ids, focused: result.movedId };
}

describe("stepMove", () => {
  it("한 칸 위나 아래로 옮긴다", () => {
    expect(stepMove(["a", "b", "c"], 1, -1)).toEqual({ from: 1, to: 0, movedId: "b" });
    expect(stepMove(["a", "b", "c"], 1, 1)).toEqual({ from: 1, to: 2, movedId: "b" });
  });

  it("위 화살표를 거듭 누르면 처음 고른 항목이 맨 위까지 계속 올라간다", () => {
    let state = { ids: ["a", "b", "c"], focused: "c" };
    state = press(state, -1);
    expect(state).toEqual({ ids: ["a", "c", "b"], focused: "c" });
    state = press(state, -1);
    expect(state).toEqual({ ids: ["c", "a", "b"], focused: "c" });
  });

  it("아래 화살표를 거듭 누르면 처음 고른 항목이 맨 아래까지 계속 내려간다", () => {
    let state = { ids: ["a", "b", "c"], focused: "a" };
    state = press(state, 1);
    expect(state).toEqual({ ids: ["b", "a", "c"], focused: "a" });
    state = press(state, 1);
    expect(state).toEqual({ ids: ["b", "c", "a"], focused: "a" });
  });

  it("끝에서 바깥으로 누르거나 모르는 자리면 옮기지 않는다", () => {
    expect(stepMove(["a", "b"], 0, -1)).toBeUndefined();
    expect(stepMove(["a", "b"], 1, 1)).toBeUndefined();
    expect(stepMove(["a", "b"], 5, -1)).toBeUndefined();
  });
});

describe("orderAfterMove", () => {
  it("옮긴 뒤의 순서를 돌려주고 원래 배열은 그대로 둔다", () => {
    const ids = ["a", "b", "c"];
    expect(orderAfterMove(ids, { from: 0, to: 2 })).toEqual(["b", "c", "a"]);
    expect(orderAfterMove(ids, { from: 2, to: 0 })).toEqual(["c", "a", "b"]);
    expect(ids).toEqual(["a", "b", "c"]);
  });
});

describe("nextAnnouncement", () => {
  it("새 문장은 그대로 넣는다", () => {
    expect(nextAnnouncement("1번째로 옮겼어요.", "2번째로 옮겼어요.")).toBe("2번째로 옮겼어요.");
  });

  it("같은 문장이 연달아 오면 값을 바꿔 다시 읽히게 하고, 세 번째도 다시 바뀐다", () => {
    const second = nextAnnouncement("규칙을 지웠어요.", "규칙을 지웠어요.");
    expect(second).not.toBe("규칙을 지웠어요.");
    expect(second.trim()).toBe("규칙을 지웠어요.");
    expect(nextAnnouncement(second, "규칙을 지웠어요.")).not.toBe(second);
  });
});
