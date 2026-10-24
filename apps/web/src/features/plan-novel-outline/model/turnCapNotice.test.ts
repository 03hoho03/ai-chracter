import { describe, expect, it } from "vitest";

import type { NovelOutlineView } from "@/entities/novel";
import { ApiErrorObject } from "@/shared/api/client";

import { countBasisTurns, toSplitTurnCounts, toTurnIndex, type OutlineEpisodeDraft, type OutlineTurn } from "./outlineEdits";
import {
  toApproveTurnCapBlock,
  toEpisodeTurnCapNotice,
  toEpisodeTurnCounts,
  toTooLongApprovalMessage,
} from "./turnCapNotice";

// 메시지 차례: u1 a1 | u2 a2 | u3 a3 a3b | u4 | u5 a5 | u6 a6 — 3턴은 응답이 둘, 4턴은 응답 없는 말 하나다.
const TURNS: OutlineTurn[] = [
  { key: "u1", number: 1, messageIds: ["u1", "a1"], responseIds: ["a1"], excerpt: "", hasResponse: true },
  { key: "u2", number: 2, messageIds: ["u2", "a2"], responseIds: ["a2"], excerpt: "", hasResponse: true },
  { key: "u3", number: 3, messageIds: ["u3", "a3", "a3b"], responseIds: ["a3", "a3b"], excerpt: "", hasResponse: true },
  { key: "u4", number: 4, messageIds: ["u4"], responseIds: [], excerpt: "", hasResponse: false },
  { key: "u5", number: 5, messageIds: ["u5", "a5"], responseIds: ["a5"], excerpt: "", hasResponse: true },
  { key: "u6", number: 6, messageIds: ["u6", "a6"], responseIds: ["a6"], excerpt: "", hasResponse: true },
];
const INDEX = toTurnIndex(TURNS);

const GEMINI = { id: "gemini", name: "Gemini", maxTurns: 45 } as const;
const SONNET = { id: "sonnet", name: "Sonnet 5.5", maxTurns: 20 } as const;
const OPUS = { id: "opus", name: "Opus 5.5", maxTurns: 20 } as const;
const CAPS = [GEMINI, SONNET, OPUS];

function range(startMessageId: string, endMessageId: string) {
  return { startMessageId, endMessageId };
}

function draft(key: string | null, basis: OutlineEpisodeDraft["basis"], chapterId: string | null = null): OutlineEpisodeDraft {
  return { localId: key ?? "split-1", key, title: "제목", summary: "줄거리", goal: "", basis, chapterId };
}

describe("근거 턴 수 — 근거 안 응답 수", () => {
  it("응답 하나가 한 턴이다 — 응답이 둘인 턴은 둘, 응답 없는 말은 0", () => {
    expect(countBasisTurns(INDEX, [range("u1", "a6")])).toBe(6);
    expect(countBasisTurns(INDEX, [range("u3", "a3b")])).toBe(2);
  });

  it("턴 가운데(응답 바로 뒤)에서 시작하는 구간은 그 뒤 응답만 센다", () => {
    expect(countBasisTurns(INDEX, [range("a3b", "a5")])).toBe(2);
  });

  it("구간이 여럿이면 더한다", () => {
    expect(countBasisTurns(INDEX, [range("u1", "a1"), range("u5", "a6")])).toBe(3);
  });

  it("근거 메시지를 지금 대화에서 못 찾으면 셀 수 없다", () => {
    expect(countBasisTurns(INDEX, [range("u1", "gone")])).toBeUndefined();
  });
});

describe("나눌 자리마다 앞뒤 턴 수", () => {
  it("자르는 메시지까지가 앞, 그 뒤가 뒤다", () => {
    expect(toSplitTurnCounts(INDEX, [range("u1", "a6")], "a3b")).toEqual({ front: 4, back: 2 });
    expect(toSplitTurnCounts(INDEX, [range("u1", "a2"), range("u5", "a6")], "a2")).toEqual({ front: 2, back: 2 });
  });

  it("근거를 못 찾으면 없다", () => {
    expect(toSplitTurnCounts(INDEX, [range("u1", "gone")], "a1")).toBeUndefined();
  });
});

describe("화마다 턴 수 — 저장 전 화는 화면이 세고, 대화를 못 받았으면 서버 값", () => {
  const view = {
    revision: 1,
    source: "generate",
    model: "gemini",
    approvedAt: null,
    createdAt: "2026-10-24T00:00:00Z",
    stale: false,
    episodes: [
      { key: "k1", title: "", summary: "", goal: "", basis: [range("u1", "a2")], chapterId: null, sceneOutline: "none", turnCount: 30 },
    ],
  } satisfies NovelOutlineView;

  it("대화를 받았으면 근거로 센다", () => {
    expect(toEpisodeTurnCounts([draft("k1", [range("u1", "a2")])], INDEX, view)).toEqual([2]);
  });

  it("대화가 없으면 근거가 서버 판과 같은 화만 서버 값을 쓰고, 고친 화·나눈 화는 모른다", () => {
    expect(
      toEpisodeTurnCounts(
        [draft("k1", [range("u1", "a2")]), draft("k1", [range("u1", "a1")]), draft(null, [range("u5", "a6")])],
        undefined,
        view,
      ),
    ).toEqual([30, undefined, undefined]);
  });
});

describe("구성안 화의 턴 상한 안내", () => {
  it("상한 안이면 없다", () => {
    expect(toEpisodeTurnCapNotice(20, CAPS)).toBeUndefined();
  });

  it("일부 모델만 넘으면 무채 안내로 쓸 수 있는 모델과 넘는 모델의 상한을 말한다", () => {
    expect(toEpisodeTurnCapNotice(21, CAPS)).toEqual({
      tone: "partial",
      message: "이 화는 21턴이라 원고는 Gemini 로만 쓸 수 있어요(Sonnet 5.5·Opus 5.5 는 20턴까지).",
    });
  });

  it("모든 모델을 넘으면 막는 안내다 — 가장 큰 상한을 말한다", () => {
    expect(toEpisodeTurnCapNotice(46, CAPS)).toEqual({
      tone: "blocking",
      message: "이 화는 46턴이라 어느 모델로도 원고를 쓸 수 없어요(45턴까지). 나눈 뒤 승인할 수 있어요.",
    });
  });

  it("Gemini 만 쓰는 계정은 45턴까지 아무것도 없다", () => {
    expect(toEpisodeTurnCapNotice(45, [GEMINI])).toBeUndefined();
    expect(toEpisodeTurnCapNotice(46, [GEMINI])?.tone).toBe("blocking");
  });

  it("턴 수를 모르거나 상한 목록이 없으면(옛 서버) 없다", () => {
    expect(toEpisodeTurnCapNotice(undefined, CAPS)).toBeUndefined();
    expect(toEpisodeTurnCapNotice(99, [])).toBeUndefined();
  });
});

describe("승인 막기 — 어느 모델로도 못 쓰는 화", () => {
  it("원고 없는 화 하나가 가장 큰 상한을 넘으면 그 화를 짚는다", () => {
    expect(
      toApproveTurnCapBlock(
        [
          { ordinal: 1, turnCount: 45, isWritten: false },
          { ordinal: 2, turnCount: 48, isWritten: false },
        ],
        CAPS,
      ),
    ).toBe("2화가 48턴이라 어느 모델로도 원고를 쓸 수 없어요(45턴까지). 나눈 뒤 승인해주세요.");
  });

  it("여럿이면 차례대로 모두 짚는다", () => {
    expect(
      toApproveTurnCapBlock(
        [
          { ordinal: 2, turnCount: 48, isWritten: false },
          { ordinal: 3, turnCount: 50, isWritten: false },
        ],
        CAPS,
      ),
    ).toBe("2화(48턴)·3화(50턴)가 45턴을 넘어 어느 모델로도 원고를 쓸 수 없어요. 나눈 뒤 승인해주세요.");
  });

  it("원고가 있는 화·셀 수 없는 화·상한 목록 없음은 막지 않는다(서버와 같다)", () => {
    expect(toApproveTurnCapBlock([{ ordinal: 1, turnCount: 99, isWritten: true }], CAPS)).toBeUndefined();
    expect(toApproveTurnCapBlock([{ ordinal: 1, turnCount: undefined, isWritten: false }], CAPS)).toBeUndefined();
    expect(toApproveTurnCapBlock([{ ordinal: 1, turnCount: 99, isWritten: false }], [])).toBeUndefined();
  });

  it("일부 모델만 넘는 화는 막지 않는다", () => {
    expect(toApproveTurnCapBlock([{ ordinal: 1, turnCount: 30, isWritten: false }], CAPS)).toBeUndefined();
  });
});

describe("승인 409 `NOVEL_OUTLINE_EPISODE_TOO_LONG` 문구", () => {
  function tooLong(detail: Record<string, unknown>) {
    return new ApiErrorObject({ status: 409, message: "x", detail: { code: "NOVEL_OUTLINE_EPISODE_TOO_LONG", ...detail } });
  }
  const episodes = [
    { key: "k1", ordinal: 4 },
    { key: "k2", ordinal: 5 },
  ];

  it("서버가 짚은 화 키를 화 번호로 바꿔 말한다", () => {
    expect(toTooLongApprovalMessage(tooLong({ maxTurns: 45, episodes: [{ key: "k2", turnCount: 48 }] }), episodes)).toBe(
      "5화가 48턴이라 어느 모델로도 원고를 쓸 수 없어요(45턴까지). 나눈 뒤 승인해주세요.",
    );
  });

  it("화를 못 짚으면(그사이 바뀜) 화 번호 없이 말한다", () => {
    expect(toTooLongApprovalMessage(tooLong({ maxTurns: 45, episodes: [{ key: "zz", turnCount: 48 }] }), episodes)).toBe(
      "어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요(45턴까지). 나눈 뒤 승인해주세요.",
    );
    // 하나만 짚으면 짚지 못한 화를 빠뜨린 채 "이 화만 나누면 된다"고 읽힌다.
    const partly = { maxTurns: 45, episodes: [{ key: "k1", turnCount: 48 }, { key: "zz", turnCount: 50 }] };
    expect(toTooLongApprovalMessage(tooLong(partly), episodes)).toBe(
      "어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요(45턴까지). 나눈 뒤 승인해주세요.",
    );
    expect(toTooLongApprovalMessage(tooLong({}), episodes)).toBe(
      "어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요. 나눈 뒤 승인해주세요.",
    );
  });

  it("다른 거절이면 없다", () => {
    const stale = new ApiErrorObject({ status: 409, message: "x", detail: { code: "NOVEL_OUTLINE_STALE" } });
    expect(toTooLongApprovalMessage(stale, episodes)).toBeUndefined();
    expect(toTooLongApprovalMessage(new Error("x"), episodes)).toBeUndefined();
  });
});
