import { describe, expect, it } from "vitest";

import type { NovelJobResponse } from "@/entities/novel";

import { toJobEpisodeKey, toRetryTarget } from "./chapterJobOutcome";

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

// 새로고침하거나 다른 탭에서 시작한 장면 구성안·원고 작업도 작업 응답의 화 키로 그 화의 확인을 다시 연다.
describe("작업 응답의 화 키로 다시 시도", () => {
  it("이 화면이 시작하지 않은 장면 구성안·원고 작업도 응답의 화 키로 다시 시도한다", () => {
    expect(toRetryTarget(job("episode_outline_generate", { episodeKey: "k3" }))).toEqual({
      kind: "episodeOutline",
      episodeKey: "k3",
    });
    expect(toRetryTarget(job("outline_chapter_generate", { episodeKey: "k3" }), { episodeKey: null })).toEqual({
      kind: "outlineChapter",
      episodeKey: "k3",
    });
  });

  it("응답에 화 키가 없으면(옛 작업) 이 화면이 기억한 키, 그것도 없으면 다시 시도가 없다", () => {
    expect(toRetryTarget(job("episode_outline_generate", { episodeKey: null }), { episodeKey: "k2" })).toEqual({
      kind: "episodeOutline",
      episodeKey: "k2",
    });
    expect(toRetryTarget(job("outline_chapter_generate", { episodeKey: null }))).toBeUndefined();
    expect(toRetryTarget(job("outline_chapter_generate"))).toBeUndefined();
  });

  it("원래 대화가 바뀌어 실패했으면 화 키가 있어도 다시 시도가 없다", () => {
    expect(
      toRetryTarget(job("episode_outline_generate", { episodeKey: "k3", failureReason: "source_changed" })),
    ).toBeUndefined();
  });

  // 스위치를 끈 서버도 모든 작업 응답에 `episodeKey: null` 을 싣는다 — 대화로 바로 만드는 작업의 다시 시도는 그대로다.
  it("대화로 바로 만드는 작업과 전체 구성안의 다시 시도는 화 키와 무관하다", () => {
    expect(toRetryTarget(job("chapter_generate", { episodeKey: null }))).toEqual({ kind: "generate" });
    expect(toRetryTarget(job("chain_generate", { episodeKey: null }))).toEqual({ kind: "generate" });
    expect(toRetryTarget(job("chapter_regenerate", { episodeKey: null, batchId: "b1" }))).toEqual({
      kind: "regenerate",
      batchId: "b1",
    });
    expect(toRetryTarget(job("outline_generate", { episodeKey: null }))).toEqual({ kind: "outline" });
    expect(toRetryTarget(job("ai_edit", { episodeKey: null }))).toBeUndefined();
  });
});

describe("toJobEpisodeKey", () => {
  it("작업이 실은 화 키가 먼저이고, 없으면 이 화면이 기억한 키, 둘 다 없으면 null 이다", () => {
    expect(toJobEpisodeKey({ episodeKey: "k1" }, "k9")).toBe("k1");
    expect(toJobEpisodeKey({ episodeKey: null }, "k9")).toBe("k9");
    expect(toJobEpisodeKey({}, undefined)).toBeNull();
    expect(toJobEpisodeKey({ episodeKey: null }, undefined)).toBeNull();
  });
});
