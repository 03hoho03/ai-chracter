import { describe, expect, it } from "vitest";

import type { NovelChapterSummary, NovelJobResponse } from "@/entities/novel";

import { OUTLINE_SPEND_FOOTNOTE, toDoneMessage, toRetryTarget } from "./chapterJobOutcome";

function job(kind: NovelJobResponse["kind"], extra: Partial<NovelJobResponse> = {}): NovelJobResponse {
  return {
    id: "job-1",
    kind,
    status: "failed",
    chargedAmount: 80,
    refunded: true,
    failureReason: "llm_error",
    chapterId: null,
    revisionId: null,
    aiEdit: null,
    createdAt: "2026-10-24T00:00:00Z",
    refundedAmount: 80,
    batchId: null,
    completedBatches: null,
    plannedBatches: null,
    ...extra,
  };
}

describe("실패한 작업의 다시 시도", () => {
  it("전체 구성안 작업은 구성안 만들기를 다시 연다", () => {
    expect(toRetryTarget(job("outline_generate"))).toEqual({ kind: "outline" });
  });

  // 고른 대화가 바뀌었으면 같은 선택으로 다시 해도 같은 실패다 — 담을 대화를 다시 승인해야 한다.
  it("고른 대화가 바뀐 구성안 실패는 다시 시도를 내밀지 않는다", () => {
    expect(toRetryTarget(job("outline_generate", { failureReason: "source_changed" }))).toBeUndefined();
  });

  it("옛 작업의 다시 시도는 그대로다", () => {
    expect(toRetryTarget(job("chapter_generate"))).toEqual({ kind: "generate" });
    expect(toRetryTarget(job("chain_generate"))).toEqual({ kind: "generate" });
    expect(toRetryTarget(job("chapter_regenerate", { batchId: "b1" }))).toEqual({ kind: "regenerate", batchId: "b1" });
    expect(toRetryTarget(job("chapter_regenerate", { failureReason: "source_changed", batchId: "b1" }))).toBeUndefined();
  });
});

describe("끝난 작업의 결과 문장", () => {
  const chapters = [
    { id: "c3", ordinal: 3, batchId: "b1" },
    { id: "c4", ordinal: 4, batchId: "b1" },
  ] as unknown as NovelChapterSummary[];

  it("전체 구성안은 화를 만들었다고 하지 않고 검토·승인을 말한다", () => {
    expect(toDoneMessage(job("outline_generate", { status: "succeeded", refundedAmount: 0 }), chapters)).toBe(
      "전체 구성안을 만들었어요. 화마다 확인한 뒤 승인해주세요.",
    );
  });

  it("옛 작업의 결과 문장은 그대로다", () => {
    expect(toDoneMessage(job("chapter_generate", { status: "succeeded", batchId: "b1", refundedAmount: 0 }), chapters)).toBe(
      "3~4화를 만들었어요.",
    );
    expect(toDoneMessage(job("chapter_regenerate", { status: "succeeded", batchId: "b1", refundedAmount: 0 }), chapters)).toBe(
      "3~4화를 다시 만들었어요.",
    );
    expect(toDoneMessage(job("chain_generate", { status: "succeeded", refundedAmount: 40 }), chapters)).toBe(
      "남은 대화를 소설로 만들었어요. 쓴 클로버 40개는 돌려드렸어요.",
    );
  });
});

describe("구성안 금액 확인의 덧붙임", () => {
  it("승인하지 않아도 돌려주지 않고, 못 만들면 모두 돌려준다고 말한다", () => {
    expect(OUTLINE_SPEND_FOOTNOTE).toBe("승인하지 않아도 쓴 클로버는 돌아오지 않아요. 만들지 못하면 모두 돌려드려요.");
  });
});
