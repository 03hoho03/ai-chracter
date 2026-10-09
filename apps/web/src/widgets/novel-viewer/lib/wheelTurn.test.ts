import { describe, expect, it } from "vitest";

import { reduceWheel, type WheelTurnEvent, type WheelTurnState } from "./wheelTurn";

const DOWN: WheelTurnEvent = { deltaX: 0, deltaY: 40, ctrlKey: false, timeStamp: 0 };

/** 이벤트 줄기를 차례로 먹이고 넘김만 모은다. */
function turnsOf(events: WheelTurnEvent[], initial: WheelTurnState = {}): number[] {
  let state = initial;
  return events.map((event) => {
    const result = reduceWheel(state, event);
    state = result.state;
    return result.turn;
  });
}

describe("reduceWheel", () => {
  it("아래로 굴리면 다음 쪽, 위로 굴리면 이전 쪽이다", () => {
    expect(reduceWheel({}, DOWN).turn).toBe(1);
    expect(reduceWheel({}, { ...DOWN, deltaY: -40 }).turn).toBe(-1);
  });

  it("트랙패드 가로 밀기도 받고, 더 크게 움직인 축을 따른다", () => {
    expect(reduceWheel({}, { ...DOWN, deltaX: 30, deltaY: 0 }).turn).toBe(1);
    expect(reduceWheel({}, { ...DOWN, deltaX: -30, deltaY: 5 }).turn).toBe(-1);
    expect(reduceWheel({}, { ...DOWN, deltaX: -5, deltaY: 30 }).turn).toBe(1);
  });

  it("관성으로 이어지는 이벤트 줄기는 한 쪽만 넘긴다", () => {
    const inertia = Array.from({ length: 60 }, (_, i) => ({ ...DOWN, timeStamp: i * 16 }));

    expect(turnsOf(inertia).filter((turn) => turn !== 0)).toEqual([1]);
  });

  it("200ms 이상 끊기면 다음 넘김을 받는다", () => {
    expect(turnsOf([DOWN, { ...DOWN, timeStamp: 199 }])).toEqual([1, 0]);
    expect(turnsOf([DOWN, { ...DOWN, timeStamp: 200 }])).toEqual([1, 1]);
  });

  it("잠긴 동안 온 이벤트가 잠금을 늘린다", () => {
    expect(turnsOf([DOWN, { ...DOWN, timeStamp: 150 }, { ...DOWN, timeStamp: 300 }])).toEqual([1, 0, 0]);
  });

  it("ctrlKey 가 붙은 휠(핀치·확대)은 넘기지도 잠그지도 않는다", () => {
    expect(reduceWheel({}, { ...DOWN, ctrlKey: true })).toEqual({ state: {}, turn: 0 });
    expect(
      turnsOf([
        { ...DOWN, ctrlKey: true },
        { ...DOWN, timeStamp: 50 },
      ]),
    ).toEqual([0, 1]);
  });

  it("움직임이 없는 이벤트는 무시한다", () => {
    expect(reduceWheel({}, { ...DOWN, deltaY: 0 })).toEqual({ state: {}, turn: 0 });
  });
});
