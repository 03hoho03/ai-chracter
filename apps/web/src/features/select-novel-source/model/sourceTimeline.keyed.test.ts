import { describe, expect, it } from "vitest";

import {
  buildSourceTurns,
  placeRangesByKey,
  restoreIncludeRanges,
  toBaseStates,
  toChangedTurnKeys,
  toSaveSections,
  type SourceMessage,
  type SourceRange,
  type TurnState,
} from "./sourceTimeline";

/** 메시지 위치 `index` 의 `createdAt`. 서버 직렬화처럼 짝수 자리는 소수부 없이, 홀수 자리는 마이크로초까지 싣는다 — 글자 비교로는
 * 순서가 틀리는 꼴을 일부러 섞는다. */
function at(index: number): string {
  const second = String(index).padStart(2, "0");
  return index % 2 === 0 ? `2026-10-24T00:00:${second}Z` : `2026-10-24T00:00:${second}.000005Z`;
}

/** 첫 인사(`a0`) 뒤에 사용자 말 `u{n}` + 응답 `a{n}` 이 한 턴. 시각은 차례대로 1초씩 늦다. */
function keyedRoom(turnCount: number): SourceMessage[] {
  const ids = ["a0"];
  for (let n = 1; n <= turnCount; n += 1) ids.push(`u${n}`, `a${n}`);
  return ids.map((id, index) => ({
    id,
    role: id.startsWith("u") ? "user" : "assistant",
    content: id,
    createdAt: at(index),
  }));
}

/** 메시지 id 로 그 메시지의 키를 단 구간. 지운 메시지를 가리켜도 키는 남는다(서버가 그대로 싣는다). */
function keyed(room: readonly SourceMessage[], startId: string, endId: string): Required<SourceRange> {
  const created = (id: string) => room.find((message) => message.id === id)?.createdAt ?? "";
  return {
    startMessageId: startId,
    endMessageId: endId,
    startMessageCreatedAt: created(startId),
    endMessageCreatedAt: created(endId),
  };
}

function without(room: readonly SourceMessage[], ...ids: string[]): SourceMessage[] {
  return room.filter((message) => !ids.includes(message.id));
}

function statesOf(turns: { key: string }[], states: Map<string, TurnState>): TurnState[] {
  return turns.map((turn) => states.get(turn.key) ?? "exclude");
}

describe("buildSourceTurns — 키로 놓는 잠금·고정 끝", () => {
  const full = keyedRoom(3);

  // 이웃으로 넓히면 이미 쓴 구간 뒤의 대화까지 모두 잠겨 담을 수 없게 된다.
  it("끝 메시지가 지워진 이미 쓴 구간은 그 끝 키까지만 잠근다", () => {
    const turns = buildSourceTurns(without(full, "a2"), {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [keyed(full, "u2", "a2")],
    });
    expect(turns.map((turn) => [turn.messageIds, turn.isLocked])).toEqual([
      [["a0"], false],
      [["u1", "a1"], false],
      [["u2"], true],
      [["u3", "a3"], false],
    ]);
  });

  it("메시지가 모두 지워진 이미 쓴 구간을 가로지르는 턴은 잠긴다 — 서버가 그 키 구간과 겹친다고 거절한다", () => {
    const room: SourceMessage[] = [
      { id: "a0", role: "assistant", content: "a0", createdAt: at(0) },
      { id: "u1", role: "user", content: "u1", createdAt: at(1) },
      { id: "a1", role: "assistant", content: "a1", createdAt: at(2) },
      { id: "x1", role: "assistant", content: "x1", createdAt: at(3) },
      { id: "u2", role: "user", content: "u2", createdAt: at(4) },
      { id: "a2", role: "assistant", content: "a2", createdAt: at(5) },
    ];
    const turns = buildSourceTurns(without(room, "a1"), {
      fixedEndId: "a2",
      roomEndId: "a2",
      lockedRanges: [keyed(room, "a1", "a1")],
    });
    expect(turns.map((turn) => [turn.messageIds, turn.isLocked])).toEqual([
      [["a0"], false],
      [["u1", "x1"], true],
      [["u2", "a2"], false],
    ]);
  });

  it("메시지가 모두 지워진 이미 쓴 구간이 두 턴 사이에 있으면 뒤 턴에서 저장 구간이 끊긴다", () => {
    const turns = buildSourceTurns(without(full, "u2", "a2"), {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [keyed(full, "u2", "a2")],
    });
    expect(turns.map((turn) => [turn.key, turn.isLocked, turn.breaksBefore])).toEqual([
      ["a0", false, false],
      ["u1", false, false],
      ["u3", false, true],
    ]);
    const states = new Map<string, TurnState>(turns.map((turn) => [turn.key, "include"]));
    expect(toSaveSections(turns, states)).toEqual([
      { mode: "include", startMessageId: "a0", endMessageId: "a1" },
      { mode: "include", startMessageId: "u3", endMessageId: "a3" },
    ]);
  });

  // 마지막 답을 다시 만들면 고른 때의 고정 끝이 지워지고 새 답이 그 뒤 시각으로 쓰인다 — 새 답은 새 대화다.
  it("지워진 고정 끝은 그 키 자리에 놓여 그 뒤 메시지는 새 턴이다", () => {
    const room = keyedRoom(2);
    const rewritten: SourceMessage[] = [
      ...without(room, "a2"),
      { id: "r2", role: "assistant", content: "다시 쓴 답", createdAt: "2026-10-24T00:01:00Z" },
    ];
    const turns = buildSourceTurns(rewritten, {
      fixedEndId: "a2",
      fixedEndCreatedAt: at(4),
      roomEndId: "r2",
      lockedRanges: [],
    });
    expect(turns.map((turn) => [turn.messageIds, turn.isNew])).toEqual([
      [["a0"], false],
      [["u1", "a1"], false],
      [["u2"], false],
      [["r2"], true],
    ]);
  });

  it("메시지나 구간에 키가 하나라도 없으면 지금처럼 이웃으로 넓혀 잠근다", () => {
    const unkeyed = without(full, "a2").map(({ createdAt: _createdAt, ...message }) => message);
    const turns = buildSourceTurns(unkeyed, {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [keyed(full, "u2", "a2")],
    });
    expect(turns.map((turn) => turn.isLocked)).toEqual([false, false, true, true]);
    expect(turns.every((turn) => !turn.breaksBefore)).toBe(true);
  });
});

describe("placeRangesByKey — 저장된 구간을 지금 있는 메시지에 맞춘다", () => {
  const full = keyedRoom(4);

  it("끝이 지워진 구간은 끝 키 이하 마지막 메시지까지다 — 다음 구간 앞까지 넓히지 않는다", () => {
    const messages = without(full, "a2");
    const placed = placeRangesByKey(messages, [
      { ...keyed(full, "u1", "a2"), mode: "include" as const },
      { ...keyed(full, "u4", "a4"), mode: "context" as const },
    ]);
    expect(placed.map((range) => [range.startMessageId, range.endMessageId, range.mode])).toEqual([
      ["u1", "u2", "include"],
      ["u4", "a4", "context"],
    ]);
    const turns = buildSourceTurns(messages, { fixedEndId: "a4", roomEndId: "a4", lockedRanges: [] });
    expect(statesOf(turns, toBaseStates(turns, placed))).toEqual(["exclude", "include", "include", "exclude", "context"]);
  });

  it("시작이 지워진 구간은 시작 키 이상 첫 메시지부터다 — 앞 구간 뒤까지 넓히지 않는다", () => {
    const messages = without(full, "a2");
    const placed = placeRangesByKey(messages, [
      { ...keyed(full, "a0", "a0"), mode: "context" as const },
      { ...keyed(full, "a2", "a3"), mode: "include" as const },
    ]);
    expect(placed.map((range) => [range.startMessageId, range.endMessageId])).toEqual([
      ["a0", "a0"],
      ["u3", "a3"],
    ]);
  });

  it("사이 메시지가 모두 지워진 구간은 빠진다", () => {
    const placed = placeRangesByKey(without(full, "u2", "a2"), [
      { ...keyed(full, "u1", "a1"), mode: "include" as const },
      { ...keyed(full, "u2", "a2"), mode: "include" as const, sourceChanged: true },
    ]);
    expect(placed.map((range) => range.startMessageId)).toEqual(["u1"]);
  });

  it("키를 모르면(메시지나 구간에 키가 없으면) 받은 그대로 둔다", () => {
    const sections = [{ startMessageId: "u1", endMessageId: "gone", mode: "include" as const }];
    expect(placeRangesByKey(without(full, "a2"), sections)).toBe(sections);
  });
});

describe("toBaseStates · toChangedTurnKeys — 자리를 알 수 없는 구간 뒤의 구간", () => {
  const room = keyedRoom(4).map(({ createdAt: _createdAt, ...message }) => message);
  const turns = buildSourceTurns(room, { fixedEndId: "a4", roomEndId: "a4", lockedRanges: [] });

  // 양 끝을 못 찾은 구간을 빼면서 뒤 구간들이 한 칸씩 앞 구간의 mode·바뀜 표시를 받았다.
  it("양 끝을 못 찾은 구간이 있어도 뒤 구간은 제 mode 다", () => {
    const states = toBaseStates(turns, [
      { startMessageId: "gone-1", endMessageId: "gone-2", mode: "include" },
      { startMessageId: "u4", endMessageId: "a4", mode: "context" },
    ]);
    expect(states.get("u4")).toBe("context");
  });

  it("양 끝을 못 찾은 구간이 있어도 뒤 구간은 제 바뀜 표시다", () => {
    const keys = toChangedTurnKeys(turns, [
      { startMessageId: "gone-1", endMessageId: "gone-2", sourceChanged: true },
      { startMessageId: "u4", endMessageId: "a4", sourceChanged: false },
    ]);
    expect([...keys]).toEqual([]);
  });
});

// 낡은 구성안의 "구간 되돌리기" — 구성안이 쓴 선택의 include 구간이 저장 때 양 끝 그대로 다시 나오게 고친다.
describe("restoreIncludeRanges", () => {
  const room = keyedRoom(6);
  const turns = buildSourceTurns(room, {
    fixedEndId: "a6",
    roomEndId: "a6",
    lockedRanges: [keyed(room, "a0", "a0")],
  });
  const current = new Map<string, TurnState>([
    ["a0", "locked"],
    ["u1", "include"],
    ["u2", "include"],
    ["u3", "exclude"],
    ["u4", "include"],
    ["u5", "exclude"],
    ["u6", "include"],
  ]);

  it("구간이 덮는 턴은 담고, 그 구간에 맞붙은 다른 담기 턴은 빼고, 떨어진 담기는 그대로 둔다", () => {
    const restored = restoreIncludeRanges(turns, current, [keyed(room, "u2", "a3")]);
    expect(restored).toBeDefined();
    expect(statesOf(turns, restored!.states)).toEqual(["locked", "exclude", "include", "include", "exclude", "exclude", "include"]);
    expect([restored!.included, restored!.excluded]).toEqual([1, 2]);
    expect(toSaveSections(turns, restored!.states)).toEqual([
      { mode: "include", startMessageId: "u2", endMessageId: "a3" },
      { mode: "include", startMessageId: "u6", endMessageId: "a6" },
    ]);
  });

  it("맥락이던 턴도 담고, 맞붙은 맥락 턴은 그대로 둔다(구간이 합쳐지지 않는다)", () => {
    const states = new Map<string, TurnState>([...current, ["u1", "context"], ["u3", "context"]]);
    const restored = restoreIncludeRanges(turns, states, [keyed(room, "u2", "a3")]);
    expect(statesOf(turns, restored!.states).slice(1, 5)).toEqual(["context", "include", "include", "exclude"]);
    expect([restored!.included, restored!.excluded]).toEqual([1, 1]);
  });

  it("이미 같으면 바꾼 것이 없다", () => {
    const restored = restoreIncludeRanges(turns, current, [keyed(room, "u1", "a2"), keyed(room, "u4", "a4")]);
    expect([restored!.included, restored!.excluded]).toEqual([0, 0]);
    expect(statesOf(turns, restored!.states)).toEqual(statesOf(turns, current));
  });

  it("양 끝이 턴 경계가 아니거나, 메시지가 없거나, 잠긴 턴이 들었거나, 두 구간이 맞붙으면 되돌릴 수 없다", () => {
    expect(restoreIncludeRanges(turns, current, [keyed(room, "a2", "a3")])).toBeUndefined();
    expect(restoreIncludeRanges(turns, current, [keyed(room, "u2", "u3")])).toBeUndefined();
    expect(restoreIncludeRanges(turns, current, [{ startMessageId: "u2", endMessageId: "gone" }])).toBeUndefined();
    expect(restoreIncludeRanges(turns, current, [keyed(room, "a0", "a1")])).toBeUndefined();
    expect(restoreIncludeRanges(turns, current, [keyed(room, "u1", "a1"), keyed(room, "u2", "a2")])).toBeUndefined();
  });

  it("받은 지도를 고치지 않는다", () => {
    restoreIncludeRanges(turns, current, [keyed(room, "u2", "a3")]);
    expect(current.get("u1")).toBe("include");
  });
});
