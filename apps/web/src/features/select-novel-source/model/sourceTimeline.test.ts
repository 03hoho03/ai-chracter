import { describe, expect, it } from "vitest";

import {
  buildSourceTurns,
  countTurnStates,
  hasIncludedResponse,
  includeTurnsInRanges,
  setTurnRange,
  setTurnsState,
  toBaseStates,
  toChangedTurnKeys,
  toggleTurn,
  toSaveSections,
  toTimelineSegments,
  type SourceMessage,
  type TurnState,
} from "./sourceTimeline";

/** 사용자 말 하나 + 응답 하나가 한 턴. 메시지 id 는 `u{n}`·`a{n}`. 맨 앞에는 사용자 말 없는 첫 인사(`a0`)가 있다. */
function room(turnCount: number): SourceMessage[] {
  const messages: SourceMessage[] = [{ id: "a0", role: "assistant", content: "*달이 떴다.* 어서 와." }];
  for (let n = 1; n <= turnCount; n += 1) {
    messages.push({ id: `u${n}`, role: "user", content: `말 ${n}` });
    messages.push({ id: `a${n}`, role: "assistant", content: `답 ${n}` });
  }
  return messages;
}

function statesOf(turns: { key: string }[], states: Map<string, TurnState>): TurnState[] {
  return turns.map((turn) => states.get(turn.key) ?? "exclude");
}

describe("buildSourceTurns", () => {
  it("사용자 말마다 새 턴을 열고, 사용자 말 앞의 첫 인사는 혼자 한 턴이다", () => {
    const turns = buildSourceTurns(room(2), { fixedEndId: "a2", roomEndId: "a2", lockedRanges: [] });
    expect(turns.map((turn) => turn.messageIds)).toEqual([["a0"], ["u1", "a1"], ["u2", "a2"]]);
    expect(turns.map((turn) => turn.number)).toEqual([1, 2, 3]);
    expect(turns.map((turn) => turn.key)).toEqual(["a0", "u1", "u2"]);
  });

  // 원고 턴 상한은 응답 하나를 한 턴으로 센다 — 턴 묶음 안의 응답을 따로 알아야 그 수를 셀 수 있다.
  it("턴마다 응답 메시지 id 를 차례대로 싣는다", () => {
    const messages: SourceMessage[] = [...room(1), { id: "a1b", role: "assistant", content: "덧붙임" }, { id: "u2", role: "user", content: "말" }];
    const turns = buildSourceTurns(messages, { fixedEndId: null, roomEndId: "u2", lockedRanges: [] });
    expect(turns.map((turn) => turn.responseIds)).toEqual([["a0"], ["a1", "a1b"], []]);
  });

  it("발췌는 응답 글에서 지문 표기를 지운 것이고, 응답이 없으면 사용자 말이다", () => {
    const messages: SourceMessage[] = [...room(1), { id: "u2", role: "user", content: "아직 답이 없는 말" }];
    const turns = buildSourceTurns(messages, { fixedEndId: "u2", roomEndId: "u2", lockedRanges: [] });
    expect(turns[0]?.excerpt).toBe("달이 떴다. 어서 와.");
    expect(turns[2]?.excerpt).toBe("아직 답이 없는 말");
    expect(turns.map((turn) => turn.hasResponse)).toEqual([true, true, false]);
  });

  it("고정 끝 뒤 메시지는 새 턴이고, 고정 끝에 걸친 턴은 고정 끝에서 나뉜다", () => {
    // 고른 때의 마지막 메시지가 사용자 말(u2)이었고 그 응답(a2)은 고른 뒤에 왔다.
    const turns = buildSourceTurns(room(3), { fixedEndId: "u2", roomEndId: "a3", lockedRanges: [] });
    expect(turns.map((turn) => [turn.messageIds, turn.isNew])).toEqual([
      [["a0"], false],
      [["u1", "a1"], false],
      [["u2"], false],
      [["a2"], true],
      [["u3", "a3"], true],
    ]);
  });

  it("화면이 본 방 끝 뒤에 온 메시지는 아직 다루지 않는다", () => {
    const turns = buildSourceTurns(room(3), { fixedEndId: "a1", roomEndId: "a2", lockedRanges: [] });
    expect(turns.at(-1)?.messageIds).toEqual(["u2", "a2"]);
  });

  // 끝을 찾지 못한 잠금을 버리면 이미 쓴 대화가 풀린 것처럼 보이고, 담으면 서버가 거절해 같은 거절이 되풀이된다.
  it("끝 메시지를 찾지 못한 이미 쓴 구간은 다음 잠금 앞(없으면 방 끝)까지 잠근다", () => {
    const turns = buildSourceTurns(room(3), {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [
        { startMessageId: "a0", endMessageId: "gone" },
        { startMessageId: "u3", endMessageId: "a3" },
      ],
    });
    expect(turns.map((turn) => turn.isLocked)).toEqual([true, true, true, true]);
    const tail = buildSourceTurns(room(3), {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [{ startMessageId: "u2", endMessageId: "gone" }],
    });
    expect(tail.map((turn) => turn.isLocked)).toEqual([false, false, true, true]);
  });

  it("이미 쓴 구간에 메시지가 하나라도 든 턴은 잠긴다", () => {
    const turns = buildSourceTurns(room(3), {
      fixedEndId: "a3",
      roomEndId: "a3",
      lockedRanges: [{ startMessageId: "a0", endMessageId: "u2" }],
    });
    expect(turns.map((turn) => turn.isLocked)).toEqual([true, true, true, false]);
  });

  it("고정 끝을 메시지 목록에서 못 찾으면 새 턴 없이 방 끝까지 다룬다", () => {
    const turns = buildSourceTurns(room(2), { fixedEndId: "gone", roomEndId: "a2", lockedRanges: [] });
    expect(turns.some((turn) => turn.isNew)).toBe(false);
    expect(turns).toHaveLength(3);
  });
});

describe("toBaseStates", () => {
  const turns = buildSourceTurns(room(4), {
    fixedEndId: "a4",
    roomEndId: "a4",
    lockedRanges: [{ startMessageId: "a0", endMessageId: "a1" }],
  });

  it("구간에 든 턴은 그 mode, 아무 구간에도 없는 턴은 빼기, 잠긴 턴은 잠김이다", () => {
    const states = toBaseStates(turns, [
      { startMessageId: "u2", endMessageId: "a2", mode: "context" },
      { startMessageId: "u4", endMessageId: "a4", mode: "include" },
    ]);
    expect(statesOf(turns, states)).toEqual(["locked", "locked", "context", "exclude", "include"]);
  });

  it("잠긴 턴도 맥락으로는 보낼 수 있어 맥락 구간이면 맥락이다", () => {
    const states = toBaseStates(turns, [{ startMessageId: "u1", endMessageId: "a1", mode: "context" }]);
    expect(states.get("u1")).toBe("context");
    expect(states.get("a0")).toBe("locked");
  });

  it("턴 가운데서 시작한 구간도 그 턴을 덮는다", () => {
    const states = toBaseStates(turns, [{ startMessageId: "a3", endMessageId: "a4", mode: "include" }]);
    expect(states.get("u3")).toBe("include");
    expect(states.get("u4")).toBe("include");
  });

  it("고정 끝 뒤 새 턴은 담기로 둔다 — 새 구간 추가로 열면 담은 채 보인다", () => {
    const withNew = buildSourceTurns(room(3), { fixedEndId: "a1", roomEndId: "a3", lockedRanges: [] });
    const states = toBaseStates(withNew, [{ startMessageId: "u1", endMessageId: "a1", mode: "include" }]);
    expect(statesOf(withNew, states)).toEqual(["exclude", "include", "include", "include"]);
  });

  // 마지막 답을 다시 만들면 담았던 구간의 끝 메시지가 새 id 가 된다. 그 구간을 버리면 담은 대화가 통째로 빼기로 보이고, 모른 채
  // 승인하면 그대로 빠진다.
  it("끝 메시지를 찾지 못한 구간은 다음 구간 앞(없으면 고정 끝)까지 넓힌다", () => {
    const states = toBaseStates(turns, [
      { startMessageId: "u2", endMessageId: "gone", mode: "include" },
      { startMessageId: "u4", endMessageId: "a4", mode: "context" },
    ]);
    expect(statesOf(turns, states)).toEqual(["locked", "locked", "include", "include", "context"]);
    const last = toBaseStates(turns, [{ startMessageId: "u3", endMessageId: "gone", mode: "include" }]);
    expect(statesOf(turns, last)).toEqual(["locked", "locked", "exclude", "include", "include"]);
  });

  it("시작 메시지를 찾지 못한 구간은 앞 구간 뒤(없으면 처음)부터로 넓힌다", () => {
    const states = toBaseStates(turns, [
      { startMessageId: "u2", endMessageId: "a2", mode: "context" },
      { startMessageId: "gone", endMessageId: "a4", mode: "include" },
    ]);
    expect(statesOf(turns, states)).toEqual(["locked", "locked", "context", "include", "include"]);
  });

  it("양 끝을 모두 찾지 못한 구간은 자리를 알 수 없어 어느 턴도 덮지 않는다", () => {
    const states = toBaseStates(turns, [{ startMessageId: "gone", endMessageId: "gone2", mode: "include" }]);
    expect(states.get("u4")).toBe("exclude");
  });

  it("고정 끝 뒤 새 턴까지는 넓히지 않는다", () => {
    const withNew = buildSourceTurns(room(3), { fixedEndId: "a2", roomEndId: "a3", lockedRanges: [] });
    const states = toBaseStates(withNew, [{ startMessageId: "u2", endMessageId: "gone", mode: "context" }]);
    expect(states.get("u2")).toBe("context");
    expect(states.get("u3")).toBe("include");
  });
});

describe("toChangedTurnKeys", () => {
  it("원문이 바뀐 구간이 덮는 턴만 고른다", () => {
    const turns = buildSourceTurns(room(3), { fixedEndId: "a3", roomEndId: "a3", lockedRanges: [] });
    const keys = toChangedTurnKeys(turns, [
      { startMessageId: "u1", endMessageId: "a1", sourceChanged: false },
      { startMessageId: "u2", endMessageId: "a3", sourceChanged: true },
    ]);
    expect([...keys]).toEqual(["u2", "u3"]);
  });
});

describe("toggleTurn · setTurnRange · setTurnsState", () => {
  const turns = buildSourceTurns(room(4), {
    fixedEndId: "a4",
    roomEndId: "a4",
    lockedRanges: [{ startMessageId: "a0", endMessageId: "a0" }],
  });
  const base = toBaseStates(turns, [{ startMessageId: "u1", endMessageId: "a2", mode: "include" }]);

  it("담기 ↔ 빼기로 바꾸고, 맥락은 누르면 담기다", () => {
    expect(toggleTurn(base, turns[1]!).get("u1")).toBe("exclude");
    expect(toggleTurn(base, turns[3]!).get("u3")).toBe("include");
    const context = setTurnsState(base, turns, ["u3"], "context");
    expect(toggleTurn(context, turns[3]!).get("u3")).toBe("include");
  });

  it("잠긴 턴은 누르면 맥락에서 잠김으로 돌아갈 뿐 담기가 되지 않는다", () => {
    expect(toggleTurn(base, turns[0]!).get("a0")).toBe("locked");
    const context = setTurnsState(base, turns, ["a0"], "context");
    expect(toggleTurn(context, turns[0]!).get("a0")).toBe("locked");
  });

  it("이어 고르기는 두 턴 사이를 모두 같은 상태로 두고 잠긴 턴은 건너뛴다", () => {
    const next = setTurnRange(base, turns, "u4", "a0", "include");
    expect(statesOf(turns, next)).toEqual(["locked", "include", "include", "include", "include"]);
    const cleared = setTurnRange(next, turns, "u1", "u3", "exclude");
    expect(statesOf(turns, cleared)).toEqual(["locked", "exclude", "exclude", "exclude", "include"]);
  });

  it("빼기 구간을 맥락으로 보내면 잠긴 턴도 맥락이 되고, 빼기로 되돌리면 잠긴 턴은 잠김으로 간다", () => {
    const context = setTurnsState(base, turns, ["a0", "u3"], "context");
    expect(context.get("a0")).toBe("context");
    const back = setTurnsState(context, turns, ["a0", "u3"], "exclude");
    expect(back.get("a0")).toBe("locked");
    expect(back.get("u3")).toBe("exclude");
  });

  it("바꾸기는 받은 지도를 고치지 않는다", () => {
    toggleTurn(base, turns[1]!);
    expect(base.get("u1")).toBe("include");
  });
});

describe("toSaveSections", () => {
  const turns = buildSourceTurns(room(5), {
    fixedEndId: "a5",
    roomEndId: "a5",
    lockedRanges: [{ startMessageId: "a0", endMessageId: "a1" }],
  });

  it("맞닿은 같은 상태의 턴은 한 구간으로 합치고, 상태가 바뀌거나 빼기·잠김이 끼면 끊는다", () => {
    const states = new Map<string, TurnState>([
      ["a0", "locked"],
      ["u1", "context"],
      ["u2", "context"],
      ["u3", "include"],
      ["u4", "exclude"],
      ["u5", "include"],
    ]);
    expect(toSaveSections(turns, states)).toEqual([
      { mode: "context", startMessageId: "u1", endMessageId: "a2" },
      { mode: "include", startMessageId: "u3", endMessageId: "a3" },
      { mode: "include", startMessageId: "u5", endMessageId: "a5" },
    ]);
  });

  it("잠긴 턴은 담기 상태가 들어와도 보내지 않는다", () => {
    const states = new Map<string, TurnState>([
      ["a0", "include"],
      ["u1", "include"],
      ["u2", "include"],
    ]);
    expect(toSaveSections(turns, states)).toEqual([{ mode: "include", startMessageId: "u2", endMessageId: "a2" }]);
  });

  it("맥락이었다가 잠김으로 돌아간 잠긴 턴 사이에서 맥락 구간이 끊긴다", () => {
    const states = new Map<string, TurnState>([
      ["a0", "context"],
      ["u1", "locked"],
      ["u2", "context"],
    ]);
    expect(toSaveSections(turns, states)).toEqual([
      { mode: "context", startMessageId: "a0", endMessageId: "a0" },
      { mode: "context", startMessageId: "u2", endMessageId: "a2" },
    ]);
  });
});

describe("hasIncludedResponse · countTurnStates", () => {
  const messages: SourceMessage[] = [...room(2), { id: "u3", role: "user", content: "답 없는 말" }];
  const turns = buildSourceTurns(messages, { fixedEndId: "u3", roomEndId: "u3", lockedRanges: [{ startMessageId: "a0", endMessageId: "a0" }] });

  it("응답이 든 턴을 하나라도 담아야 참이다 — 사용자 말뿐인 턴만 담으면 거짓", () => {
    expect(hasIncludedResponse(turns, new Map([["u3", "include"]]))).toBe(false);
    expect(hasIncludedResponse(turns, new Map([["u2", "context"]]))).toBe(false);
    expect(hasIncludedResponse(turns, new Map([["u2", "include"]]))).toBe(true);
  });

  it("상태마다 턴 수를 센다", () => {
    const states = new Map<string, TurnState>([
      ["a0", "locked"],
      ["u1", "include"],
      ["u2", "context"],
    ]);
    expect(countTurnStates(turns, states)).toEqual({ include: 1, context: 1, exclude: 1, locked: 1 });
  });
});

describe("toTimelineSegments", () => {
  it("맞닿은 같은 상태의 턴을 한 묶음으로 모은다", () => {
    const turns = buildSourceTurns(room(4), { fixedEndId: "a4", roomEndId: "a4", lockedRanges: [{ startMessageId: "a0", endMessageId: "a0" }] });
    const states = new Map<string, TurnState>([
      ["a0", "locked"],
      ["u1", "include"],
      ["u2", "include"],
      ["u3", "exclude"],
      ["u4", "context"],
    ]);
    expect(toTimelineSegments(turns, states).map((segment) => [segment.state, segment.turns.map((turn) => turn.number)])).toEqual([
      ["locked", [1]],
      ["include", [2, 3]],
      ["exclude", [4]],
      ["context", [5]],
    ]);
  });
});

// 구성안이 낡았을 때 "구간 되돌리기" — 구성안이 근거로 쓴 대화 가운데 지금 담기에 없는 턴을 다시 담는다.
describe("includeTurnsInRanges", () => {
  const turns = buildSourceTurns(room(5), {
    fixedEndId: "a5",
    roomEndId: "a5",
    lockedRanges: [{ startMessageId: "a0", endMessageId: "a0" }],
  });
  const states = toBaseStates(turns, [{ mode: "include", startMessageId: "u1", endMessageId: "a1" }]);

  it("구간이 덮는 턴 중 담기가 아닌 것만 담기로 바꾸고 바꾼 수를 센다", () => {
    const result = includeTurnsInRanges(turns, states, [
      { startMessageId: "u1", endMessageId: "a1" },
      { startMessageId: "u3", endMessageId: "a4" },
    ]);
    expect(statesOf(turns, result.states)).toEqual(["locked", "include", "exclude", "include", "include", "exclude"]);
    expect(result.count).toBe(2);
  });

  it("잠긴 턴은 담지 않고, 지금 대화에 없는 구간은 건너뛴다", () => {
    const result = includeTurnsInRanges(turns, states, [
      { startMessageId: "a0", endMessageId: "a0" },
      { startMessageId: "gone-1", endMessageId: "gone-2" },
    ]);
    expect(result.count).toBe(0);
    expect(statesOf(turns, result.states)).toEqual(statesOf(turns, states));
  });
});
