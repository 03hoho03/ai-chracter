import { describe, expect, it } from "vitest";

import { stepStatRule } from "./statRuleOrder";

/** 화면처럼 포커스가 있는 규칙의 지금 자리에서 화살표를 누르고, 목록과 포커스를 이동 뒤 상태로 돌려준다. */
function press(state: { ids: string[]; focused: string }, step: -1 | 1) {
  const result = stepStatRule(state.ids, state.ids.indexOf(state.focused), step);
  if (!result) return state;
  const ids = [...state.ids];
  const [moved] = ids.splice(result.from, 1);
  if (moved !== undefined) ids.splice(result.to, 0, moved);
  return { ids, focused: result.focusRuleId };
}

describe("stepStatRule", () => {
  it("위 화살표를 거듭 누르면 처음 고른 규칙이 맨 위까지 계속 올라간다", () => {
    let state = { ids: ["a", "b", "c"], focused: "c" };
    state = press(state, -1);
    expect(state).toEqual({ ids: ["a", "c", "b"], focused: "c" });
    state = press(state, -1);
    expect(state).toEqual({ ids: ["c", "a", "b"], focused: "c" });
  });

  it("아래 화살표를 거듭 누르면 처음 고른 규칙이 맨 아래까지 계속 내려간다", () => {
    let state = { ids: ["a", "b", "c"], focused: "a" };
    state = press(state, 1);
    expect(state).toEqual({ ids: ["b", "a", "c"], focused: "a" });
    state = press(state, 1);
    expect(state).toEqual({ ids: ["b", "c", "a"], focused: "a" });
  });

  it("끝에서 바깥으로 누르면 옮기지 않는다", () => {
    expect(stepStatRule(["a", "b"], 0, -1)).toBeUndefined();
    expect(stepStatRule(["a", "b"], 1, 1)).toBeUndefined();
    expect(stepStatRule(["a", "b"], 5, -1)).toBeUndefined();
  });
});
