import { describe, expect, it } from "vitest";

import { splitEpisode, toSplitPoints, toTurnIndex, type OutlineRange } from "@/features/plan-novel-outline";
import { buildSourceTurns, type SourceMessage } from "@/features/select-novel-source";

/**
 * 서버가 구성안 저장에서 근거 구간의 턴 경계를 보는 법을 그대로 옮긴 기준 — 구간 끝은 모델 응답이어야 하고, 구간 시작은 그 담기 구간의
 * 첫 메시지이거나 모델 응답 바로 뒤 메시지여야 한다(그래야 사용자 말과 그 응답이 두 화로 갈리지 않는다). 이 고정 데이터는 방 전체가
 * 담기 구간 하나다.
 */
function serverAcceptsBasis(messages: readonly SourceMessage[], basis: readonly OutlineRange[]): boolean {
  if (basis.length === 0) return false;
  return basis.every((range) => {
    const first = messages.findIndex((message) => message.id === range.startMessageId);
    const last = messages.findIndex((message) => message.id === range.endMessageId);
    if (first < 0 || last < first) return false;
    return messages[last]?.role === "assistant" && (first === 0 || messages[first - 1]?.role === "assistant");
  });
}

/** 근거를 메시지 `cutId` 뒤에서 앞뒤로 가른 두 근거 — 화면 구현과 따로 메시지 차례만으로 자른다. */
function cutBasis(messages: readonly SourceMessage[], basis: readonly OutlineRange[], cutId: string) {
  const at = (id: string) => messages.findIndex((message) => message.id === id);
  const cut = at(cutId);
  const front: OutlineRange[] = [];
  const back: OutlineRange[] = [];
  for (const range of basis) {
    const start = at(range.startMessageId);
    const end = at(range.endMessageId);
    if (end <= cut) front.push(range);
    else if (start > cut) back.push(range);
    else {
      front.push({ startMessageId: range.startMessageId, endMessageId: cutId });
      back.push({ startMessageId: messages[cut + 1]?.id ?? "", endMessageId: range.endMessageId });
    }
  }
  return { front, back };
}

/** 서버가 받는 나눌 자리 — 화 근거 안의 메시지마다 거기서 자른 앞뒤 근거가 둘 다 비지 않고 서버 검증을 지나는지. */
function serverSplitCuts(messages: readonly SourceMessage[], basis: readonly OutlineRange[]): string[] {
  const at = (id: string) => messages.findIndex((message) => message.id === id);
  const inBasis = messages.filter((_, position) =>
    basis.some((range) => at(range.startMessageId) <= position && position <= at(range.endMessageId)),
  );
  return inBasis
    .map((message) => message.id)
    .filter((cutId) => {
      const { front, back } = cutBasis(messages, basis, cutId);
      return serverAcceptsBasis(messages, front) && serverAcceptsBasis(messages, back);
    });
}

function user(id: string): SourceMessage {
  return { id, role: "user", content: id };
}

function assistant(id: string): SourceMessage {
  return { id, role: "assistant", content: id };
}

// 방 맨 앞 첫 인사 둘(사용자 말 없는 응답 연달아), 응답이 셋 붙은 턴, 응답 없는 말이 낀 턴까지 — 화면의 턴 묶음 끝과 서버가 받는
// 자리가 갈리는 곳을 모두 담는다.
const MESSAGES: SourceMessage[] = [
  assistant("a0"),
  assistant("a0b"),
  user("u1"),
  assistant("a1"),
  user("u2"),
  assistant("a2"),
  assistant("a2b"),
  assistant("a2c"),
  user("u3"),
  user("u4"),
  assistant("a4"),
  user("u5"),
  assistant("a5"),
  user("u6"),
  assistant("a6"),
];

const index = toTurnIndex(buildSourceTurns(MESSAGES, { fixedEndId: null, roomEndId: "a6", lockedRanges: [] }));

const CASES: { name: string; basis: OutlineRange[] }[] = [
  { name: "첫 인사 둘부터", basis: [{ startMessageId: "a0", endMessageId: "a1" }] },
  { name: "첫 인사 둘뿐", basis: [{ startMessageId: "a0", endMessageId: "a0b" }] },
  { name: "응답이 셋 붙은 턴", basis: [{ startMessageId: "u2", endMessageId: "a2c" }] },
  { name: "같은 턴의 두 번째 응답에서 시작", basis: [{ startMessageId: "a2b", endMessageId: "a4" }] },
  { name: "응답 없는 말이 낀 구간", basis: [{ startMessageId: "u3", endMessageId: "a5" }] },
  {
    name: "구간 둘",
    basis: [
      { startMessageId: "a0", endMessageId: "a0b" },
      { startMessageId: "u3", endMessageId: "a6" },
    ],
  },
  { name: "응답 하나뿐", basis: [{ startMessageId: "u1", endMessageId: "a1" }] },
  { name: "방 전체", basis: [{ startMessageId: "a0", endMessageId: "a6" }] },
];

describe("구성안 나눌 자리 — 화면이 내놓는 자리 = 서버가 받는 자리", () => {
  it.each(CASES)("$name", ({ basis }) => {
    expect(serverAcceptsBasis(MESSAGES, basis)).toBe(true);
    const offered = toSplitPoints(index, basis).map((point) => point.cutMessageId);
    expect(offered).toEqual(serverSplitCuts(MESSAGES, basis));
  });

  it.each(CASES)("$name — 내놓은 자리마다 나눈 두 화의 근거를 서버가 받고, 다른 자리는 나누지 않는다", ({ basis }) => {
    const episode = { localId: "e", key: "e", title: "화", summary: "줄거리", goal: "", basis, chapterId: null };
    const accepted = new Set(serverSplitCuts(MESSAGES, basis));
    for (const message of MESSAGES) {
      const result = splitEpisode([episode], "e", message.id, index, "new");
      if (!accepted.has(message.id)) {
        expect(result).toBeUndefined();
        continue;
      }
      expect(result?.map((item) => item.basis)).toEqual(Object.values(cutBasis(MESSAGES, basis, message.id)));
      for (const item of result ?? []) expect(serverAcceptsBasis(MESSAGES, item.basis)).toBe(true);
    }
  });

  // 화면의 턴 묶음(사용자 말 하나와 그 뒤 응답들) 끝에서만 자르면 첫 인사 둘 사이·연달은 응답 사이를 놓친다 — 이 데이터에서 둘이
  // 실제로 갈려야 위 등식이 응답마다 자른다는 것을 보인다.
  it("턴 묶음 끝과 서버가 받는 자리가 이 데이터에서 실제로 다르다", () => {
    const turnEnds = index.turns.filter((turn) => turn.hasResponse).map((turn) => turn.messageIds.at(-1));
    const whole = [{ startMessageId: "a0", endMessageId: "a6" }];
    expect(serverSplitCuts(MESSAGES, whole)).toEqual(expect.arrayContaining(["a0", "a2", "a2b"]));
    expect(turnEnds).not.toContain("a0");
    expect(turnEnds).not.toContain("a2");
  });
});
