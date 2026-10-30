import { describe, expect, it } from "vitest";

import type { CallCostView } from "@/shared/api/client";

import { generationCardCount, groupCalls, MISSING_CALL_SITE } from "./callGroups";

function call(kind: CallCostView["kind"], callSite: string): CallCostView {
  return {
    callSite,
    kind,
    model: "model",
    promptTokens: 10,
    cachedTokens: 0,
    cacheWriteTokens: 0,
    outputTokens: 1,
    thoughtsTokens: null,
    newInputTokens: 10,
    usd: 0.001,
    missingTokens: false,
    firstTokenMs: null,
    streamFirstTokenMs: null,
  };
}

describe("groupCalls", () => {
  it("묶음은 측정 서버가 낸 종류를 따른다 — call_site 이름이 생성·판정처럼 보여도 이름으로 가르지 않는다", () => {
    const generationLike = call("other", "chat_generate");
    const judgmentLike = call("other", "chat_stat_judgment");
    const judgment = call("judgment", "ending_check");
    const generation = call("generation", "chat_stream");

    const groups = groupCalls([generationLike, judgmentLike, judgment, generation], []);

    expect(groups.generation).toEqual([generation]);
    expect(groups.judgment).toEqual([{ callSite: "ending_check", calls: [judgment], dumpIndexes: [] }]);
    expect(groups.other).toEqual([generationLike, judgmentLike]);
  });

  it("백그라운드는 따로, 임베딩과 그 밖은 '그 밖'에 — 기록 순서를 지킨다", () => {
    const background = call("background", "memory_summary");
    const embedding = call("embedding", "query_embedding");
    const other = call("other", "unknown_site");

    const groups = groupCalls([other, background, embedding], []);

    expect(groups.background).toEqual([background]);
    expect(groups.other).toEqual([other, embedding]);
    expect(groups.generation).toEqual([]);
  });

  it("판정 덤프 줄과 판정 호출을 call_site 끼리 묶고, 덤프 순번은 그 턴 판정 덤프 목록에서 1부터 센다", () => {
    const statCall = call("judgment", "chat_stat_judgment");
    const groups = groupCalls(
      [statCall],
      [{ callSite: "chat_stat_judgment" }, { callSite: "ending_judgment" }, { callSite: "chat_stat_judgment" }],
    );

    expect(groups.judgment).toEqual([
      { callSite: "chat_stat_judgment", calls: [statCall], dumpIndexes: [1, 3] },
      { callSite: "ending_judgment", calls: [], dumpIndexes: [2] },
    ]);
  });

  it("판정 묶음은 덤프 줄에서 본 call_site 가 앞, 덤프 줄 없이 호출만 있는 call_site 가 뒤다", () => {
    const callOnly = call("judgment", "late_judgment");
    const groups = groupCalls([callOnly], [{ callSite: "dumped_judgment" }]);

    expect(groups.judgment.map((site) => site.callSite)).toEqual(["dumped_judgment", "late_judgment"]);
  });

  it("call_site 칸이 없거나 글이 아닌 판정 덤프 줄은 'call_site 없음' 묶음에 모은다", () => {
    const groups = groupCalls([], [{}, { callSite: 3 }]);

    expect(groups.judgment).toEqual([{ callSite: MISSING_CALL_SITE, calls: [], dumpIndexes: [1, 2] }]);
    expect(MISSING_CALL_SITE).toBe("call_site 없음");
  });

  it("호출도 덤프 줄도 없으면 모든 묶음이 빈다", () => {
    expect(groupCalls([], [])).toEqual({ generation: [], judgment: [], background: [], other: [] });
  });
});

describe("generationCardCount", () => {
  it("턴 기록의 생성 호출이 있으면 그 호출 수, 없으면 덤프로 그리는 카드 하나 — 머리 숫자가 보이는 카드 수와 같다", () => {
    const first = call("generation", "chat_generate");
    const second = call("generation", "chat_generate");

    expect(generationCardCount(groupCalls([first, second], []))).toBe(2);
    expect(generationCardCount(groupCalls([call("judgment", "chat_stat_judgment")], []))).toBe(1);
    expect(generationCardCount(groupCalls([], []))).toBe(1);
  });
});
