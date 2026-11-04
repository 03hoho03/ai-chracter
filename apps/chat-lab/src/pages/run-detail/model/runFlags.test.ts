import { describe, expect, it } from "vitest";

import type { ReplyFlagsView, TurnMetrics } from "@/shared/api/client";

import { flaggedTurns, type RunFlagKey } from "./runFlags";

function metrics(turn: number, overrides: Partial<ReplyFlagsView> = {}): TurnMetrics {
  return {
    turn,
    previousFrom: "turn",
    previousTurn: turn - 1,
    flags: {
      length: 10,
      sentenceCount: 1,
      statusBlockLength: 0,
      truncated: false,
      selfCopy: false,
      solicit: false,
      ignored: false,
      sceneOpen: false,
      labelLeak: false,
      userTurn: false,
      broken: null,
      brackets: [],
      ...overrides,
    },
  };
}

describe("flaggedTurns", () => {
  const turns = [
    metrics(1, { solicit: true }),
    metrics(2, { selfCopy: true, broken: "" }),
    metrics(4, { solicit: true, brackets: ["()"] }),
  ];

  it("참/거짓 플래그는 그 플래그가 선 턴 번호를 표본 순서대로", () => {
    expect(flaggedTurns(turns, "solicit")).toEqual([1, 4]);
    expect(flaggedTurns(turns, "selfCopy")).toEqual([2]);
    expect(flaggedTurns(turns, "truncated")).toEqual([]);
  });

  it("깨짐은 까닭 글이 있으면(빈 글이어도) 선 것이고, 괄호는 하나라도 있으면 선 것이다 — 런 요약의 셈과 같다", () => {
    expect(flaggedTurns(turns, "broken")).toEqual([2]);
    expect(flaggedTurns(turns, "brackets")).toEqual([4]);
  });
});

/** 플래그마다 그 플래그만 세우는 턴 칸 — 키를 빠뜨리면 타입이 멈춘다. */
const RAISE_ONLY = {
  truncated: { truncated: true },
  selfCopy: { selfCopy: true },
  labelLeak: { labelLeak: true },
  userTurn: { userTurn: true },
  solicit: { solicit: true },
  ignored: { ignored: true },
  sceneOpen: { sceneOpen: true },
  broken: { broken: "닫히지 않은 괄호" },
  brackets: { brackets: ["()"] },
} as const satisfies Record<RunFlagKey, Partial<ReplyFlagsView>>;

const KEYS = Object.keys(RAISE_ONLY).filter((key): key is RunFlagKey => Object.hasOwn(RAISE_ONLY, key));

describe("flaggedTurns 플래그별 표", () => {
  // 턴 n 은 KEYS[n-1] 하나만 선 턴이다.
  const table = KEYS.map((key, order) => metrics(order + 1, RAISE_ONLY[key]));

  it.each(KEYS.map((key, order) => [key, order + 1] as const))("%s 는 그 플래그만 선 턴(%i) 하나만 고른다", (key, turn) => {
    expect(flaggedTurns(table, key)).toEqual([turn]);
  });

  it("표가 런 요약이 세는 플래그 아홉을 모두 덮는다", () => {
    expect(KEYS).toHaveLength(9);
  });
});
