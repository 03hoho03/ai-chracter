import { describe, expect, it } from "vitest";

import type { NovelChapterSummary, NovelJobResponse } from "@/entities/novel";

import { toDoneMessage, toRetryTarget } from "./chapterJobOutcome";

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

const chapters = [
  { id: "c1", ordinal: 1, batchId: "b1", episodeOutlineId: null },
  { id: "c2", ordinal: 2, batchId: "b2", episodeOutlineId: "eo-2" },
] as unknown as NovelChapterSummary[];

describe("구성 흐름 작업의 다시 시도", () => {
  it("구성안으로 쓴 화의 다시 만들기 실패는 새 라우트의 확인을 다시 연다(옛 라우트는 409)", () => {
    expect(toRetryTarget(job("chapter_regenerate", { chapterId: "c2", batchId: "b2" }), { chapters })).toEqual({
      kind: "outlineRegenerate",
      chapterId: "c2",
    });
  });

  it("작업이 묶음만 가리켜도 그 묶음의 화로 가른다", () => {
    expect(toRetryTarget(job("chapter_regenerate", { batchId: "b2" }), { chapters })).toEqual({
      kind: "outlineRegenerate",
      chapterId: "c2",
    });
  });

  it("대화로 바로 만든 화의 다시 만들기는 그대로 묶음 확인이다", () => {
    expect(toRetryTarget(job("chapter_regenerate", { chapterId: "c1", batchId: "b1" }), { chapters })).toEqual({
      kind: "regenerate",
      batchId: "b1",
    });
  });

  it("장면 구성안·원고 실패는 화 키를 알 때만 그 화의 확인을 다시 연다", () => {
    expect(toRetryTarget(job("episode_outline_generate"), { chapters, episodeKey: "k3" })).toEqual({
      kind: "episodeOutline",
      episodeKey: "k3",
    });
    expect(toRetryTarget(job("outline_chapter_generate"), { chapters, episodeKey: "k3" })).toEqual({
      kind: "outlineChapter",
      episodeKey: "k3",
    });
    expect(toRetryTarget(job("episode_outline_generate"), { chapters })).toBeUndefined();
    expect(toRetryTarget(job("outline_chapter_generate"), { chapters, episodeKey: null })).toBeUndefined();
  });

  it("원문이 바뀐 실패는 어느 종류든 다시 시도를 내밀지 않는다", () => {
    const changed = { failureReason: "source_changed" as const };
    expect(toRetryTarget(job("chapter_regenerate", { ...changed, chapterId: "c2", batchId: "b2" }), { chapters })).toBeUndefined();
    expect(toRetryTarget(job("episode_outline_generate", changed), { chapters, episodeKey: "k3" })).toBeUndefined();
    expect(toRetryTarget(job("outline_chapter_generate", changed), { chapters, episodeKey: "k3" })).toBeUndefined();
  });
});

describe("구성 흐름 작업의 결과 문장", () => {
  it("장면 구성안은 확인·승인을 말한다", () => {
    expect(toDoneMessage(job("episode_outline_generate", { status: "succeeded", refundedAmount: 0 }), chapters)).toBe(
      "장면 구성안을 만들었어요. 장면을 확인한 뒤 승인해주세요.",
    );
  });

  it("원고는 쓴 화 번호를 말한다", () => {
    expect(
      toDoneMessage(job("outline_chapter_generate", { status: "succeeded", refundedAmount: 0, chapterId: "c2", batchId: "b2" }), chapters),
    ).toBe("2화를 썼어요.");
    expect(toDoneMessage(job("outline_chapter_generate", { status: "succeeded", refundedAmount: 0 }), chapters)).toBe(
      "구성안으로 새 화를 썼어요.",
    );
  });

  it("구성안으로 쓴 화의 다시 만들기는 옛 문장 그대로다", () => {
    expect(
      toDoneMessage(job("chapter_regenerate", { status: "succeeded", refundedAmount: 0, chapterId: "c2", batchId: "b2" }), chapters),
    ).toBe("2화를 다시 만들었어요.");
  });
});
