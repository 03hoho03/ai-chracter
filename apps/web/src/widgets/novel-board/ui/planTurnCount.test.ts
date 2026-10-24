import { describe, expect, it } from "vitest";

import { countBasisTurns, toTurnIndex, type OutlineRange } from "@/features/plan-novel-outline";
import { buildSourceTurns, type SourceMessage } from "@/features/select-novel-source";

/**
 * 서버가 구성안 화의 턴 수(`turnCount`)와 원고 턴 상한을 세는 법을 그대로 옮긴 기준 — 근거 구간마다 그 구간 메시지를 대화 차례로
 * 읽어 턴으로 묶고(사용자 말은 뒤에 오는 응답과 한 턴, 응답 하나가 턴 하나, 끝에 남은 응답 없는 말은 버림) 그 턴 수를 더한다.
 * 화면은 저장 전 화(나눈 조각·합친 결과)를 이 수와 같게 세야 상한 안내가 서버의 승인 거절·원고 거절과 어긋나지 않는다.
 */
function serverTurnCount(messages: readonly SourceMessage[], basis: readonly OutlineRange[]): number {
  let total = 0;
  for (const range of basis) {
    const start = messages.findIndex((message) => message.id === range.startMessageId);
    const end = messages.findIndex((message) => message.id === range.endMessageId);
    let turns = 0;
    for (const message of messages.slice(start, end + 1)) {
      // 사용자 말은 다음 응답의 턴에 붙을 뿐 턴을 열지 않는다 — 응답이 오지 않으면 버려진다.
      if (message.role === "user") continue;
      turns += 1;
    }
    total += turns;
  }
  return total;
}

function user(id: string): SourceMessage {
  return { id, role: "user", content: id };
}

function assistant(id: string): SourceMessage {
  return { id, role: "assistant", content: id };
}

// 방 맨 앞 첫 인사 둘(사용자 말 없는 응답 연달아), 응답이 둘 붙은 턴, 응답 없는 말, 같은 턴 안 두 번째 응답에서 시작하는 근거까지 —
// 턴 묶음 수와 응답 수가 갈리는 자리를 모두 담는다.
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

const turns = buildSourceTurns(MESSAGES, { fixedEndId: null, roomEndId: "a6", lockedRanges: [] });
const index = toTurnIndex(turns);

const CASES: { name: string; basis: OutlineRange[] }[] = [
  { name: "첫 인사 둘부터", basis: [{ startMessageId: "a0", endMessageId: "a1" }] },
  { name: "응답이 셋 붙은 턴", basis: [{ startMessageId: "u2", endMessageId: "a2c" }] },
  { name: "같은 턴의 두 번째 응답에서 시작", basis: [{ startMessageId: "a2b", endMessageId: "a4" }] },
  { name: "응답 없는 말이 낀 구간", basis: [{ startMessageId: "u3", endMessageId: "a5" }] },
  {
    name: "구간 둘",
    basis: [
      { startMessageId: "a0", endMessageId: "a0b" },
      { startMessageId: "u4", endMessageId: "a6" },
    ],
  },
  { name: "방 전체", basis: [{ startMessageId: "a0", endMessageId: "a6" }] },
];

describe("구성안 화 턴 수 — 화면 세기 = 서버 세기", () => {
  it.each(CASES)("$name", ({ basis }) => {
    expect(countBasisTurns(index, basis)).toBe(serverTurnCount(MESSAGES, basis));
  });

  // 턴 묶음(사용자 말 하나와 그 뒤 응답들)으로 세면 응답이 연달아 있을 때 서버보다 적다 — 이 고정 데이터에서 둘이 실제로 갈려야
  // 위 등식이 응답 수로 센다는 것을 보인다.
  it("턴 묶음 수와 응답 수가 이 데이터에서 실제로 다르다", () => {
    expect(turns.length).toBe(7);
    expect(countBasisTurns(index, [{ startMessageId: "a0", endMessageId: "a6" }])).toBe(9);
  });
});
