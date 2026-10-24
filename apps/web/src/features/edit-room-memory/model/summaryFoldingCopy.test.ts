import { describe, expect, it } from "vitest";

import { summaryFoldingCopy } from "./summaryFoldingCopy";

describe("summaryFoldingCopy", () => {
  it("keeps today's sentences while long conversations are folded into the summary", () => {
    expect(summaryFoldingCopy(true)).toEqual({
      emptySummary: "아직 요약할 만큼 대화가 쌓이지 않았어요. 최근 대화는 전부 기억 중이에요.",
      foldingHint: "대화를 이어 가면 AI가 이 요약을 다시 정리해요. 꼭 지켜야 할 내용은 ‘꼭 기억할 것’에 적어 주세요.",
    });
  });

  it("does not claim the AI keeps summarizing while folding is switched off", () => {
    const copy = summaryFoldingCopy(false);
    expect(copy).toEqual({
      emptySummary: "지금은 대화를 요약으로 정리하지 않아요.",
      foldingHint: "지금은 대화를 요약으로 정리하지 않고, 요약도 응답에 쓰이지 않아요. 지난 대화는 그대로 기억하고 있어요.",
    });
    expect(copy.foldingHint).not.toContain("다시 정리해요");
  });
});
