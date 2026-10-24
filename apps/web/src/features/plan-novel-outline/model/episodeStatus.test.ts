import { describe, expect, it } from "vitest";

import type { NovelEpisodeOutlineState, NovelEpisodeOutlineView } from "@/entities/novel";

import {
  toEpisodeOutlineBase,
  toManuscriptProgressLine,
  toManuscriptStatuses,
  toSceneMakeBlockedReason,
  toWriteBlockedReason,
} from "./episodeStatus";

function view(revision: number, extra: Partial<NovelEpisodeOutlineView> = {}): NovelEpisodeOutlineView {
  return {
    revision,
    source: "generate",
    model: "gemini",
    approvedAt: null,
    createdAt: "2026-10-24T00:00:00Z",
    stale: false,
    scenes: [],
    ...extra,
  };
}

function state(parts: Partial<NovelEpisodeOutlineState>): NovelEpisodeOutlineState {
  return { episodeKey: "k1", approved: null, draft: null, models: [], chapterModels: [], chapterId: null, ...parts };
}

describe("장면 구성안 판", () => {
  it("초안이 승인본보다 먼저이고, 없으면 승인본, 둘 다 없으면 없다", () => {
    expect(toEpisodeOutlineBase(state({}))).toBeUndefined();
    const approved = view(1, { approvedAt: "2026-10-24T01:00:00Z" });
    expect(toEpisodeOutlineBase(state({ approved }))).toEqual({ view: approved, status: "approved", isStale: false });
    const draft = view(2, { stale: true });
    expect(toEpisodeOutlineBase(state({ approved, draft }))).toEqual({ view: draft, status: "draft", isStale: true });
  });
});

describe("원고 차례", () => {
  it("앞 화가 모두 원고면 첫 빈 화가 쓸 차례이고, 그 뒤는 앞 화 먼저다", () => {
    expect(toManuscriptStatuses([{ chapterId: "c1" }, { chapterId: null }, { chapterId: null }])).toEqual([
      { kind: "written", chapterId: "c1" },
      { kind: "next" },
      { kind: "waiting" },
    ]);
  });

  it("뒤 화에 원고가 있으면 앞의 빈 화는 쓸 수 없다(서버 순서 규칙과 같다)", () => {
    expect(toManuscriptStatuses([{ chapterId: null }, { chapterId: "c2" }])).toEqual([
      { kind: "laterWritten" },
      { kind: "written", chapterId: "c2" },
    ]);
  });

  it("바로 앞 화만이 아니라 앞 화 모두가 원고여야 쓸 차례다", () => {
    expect(toManuscriptStatuses([{ chapterId: null }, { chapterId: "c2" }, { chapterId: null }])[2]).toEqual({ kind: "waiting" });
  });

  it("개요 한 줄은 원고 수를 센다", () => {
    expect(toManuscriptProgressLine([{ chapterId: "c1" }, { chapterId: null }, { chapterId: null }])).toBe(
      "화별 장면·원고 · 원고 1/3화",
    );
  });
});

const READY = {
  isRoomGone: false,
  isJobRunning: false,
  isAiEditRunning: false,
  outline: "ok" as const,
  isWritten: false,
  isDirty: false,
};

describe("장면 구성안 만들기 막힘", () => {
  it("막을 것이 없으면 없다", () => {
    expect(toSceneMakeBlockedReason(READY)).toBeUndefined();
  });

  it("앞의 이유가 먼저다", () => {
    expect(toSceneMakeBlockedReason({ ...READY, isRoomGone: true, isJobRunning: true })).toBe(
      "원래 대화방이 지워져 장면 구성안을 새로 만들 수 없어요.",
    );
    expect(toSceneMakeBlockedReason({ ...READY, isJobRunning: true, isAiEditRunning: true })).toBe(
      "다른 작업이 끝나면 만들 수 있어요.",
    );
    expect(toSceneMakeBlockedReason({ ...READY, isAiEditRunning: true })).toBe("AI로 고치는 중이에요. 끝나면 만들 수 있어요.");
    expect(toSceneMakeBlockedReason({ ...READY, outline: "missing" })).toBe("전체 구성안을 먼저 승인해주세요.");
    expect(toSceneMakeBlockedReason({ ...READY, outline: "stale" })).toBe(
      "전체 구성안이 낡아 장면 구성안을 만들 수 없어요. 전체 구성안을 먼저 바로잡아주세요.",
    );
    expect(toSceneMakeBlockedReason({ ...READY, isWritten: true })).toBe("원고를 쓴 화는 장면 구성안을 새로 만들지 않아요.");
    expect(toSceneMakeBlockedReason({ ...READY, isDirty: true })).toBe("고친 장면 구성안을 먼저 저장하거나 되돌려주세요.");
  });
});

const WRITABLE = {
  isRoomGone: false,
  isJobRunning: false,
  isAiEditRunning: false,
  outline: "ok" as const,
  order: "next" as const,
  hasApproved: true,
  hasNewerDraft: false,
  isApprovedStale: false,
  isDirty: false,
};

describe("원고 쓰기 막힘", () => {
  it("쓸 수 있으면 없다", () => {
    expect(toWriteBlockedReason(WRITABLE)).toBeUndefined();
  });

  it("이유마다 문장이 있다", () => {
    expect(toWriteBlockedReason({ ...WRITABLE, isRoomGone: true })).toBe("원래 대화방이 지워져 원고를 쓸 수 없어요.");
    expect(toWriteBlockedReason({ ...WRITABLE, isJobRunning: true })).toBe("다른 작업이 끝나면 쓸 수 있어요.");
    expect(toWriteBlockedReason({ ...WRITABLE, isAiEditRunning: true })).toBe("AI로 고치는 중이에요. 끝나면 쓸 수 있어요.");
    expect(toWriteBlockedReason({ ...WRITABLE, outline: "stale" })).toBe(
      "전체 구성안이 낡아 원고를 쓸 수 없어요. 전체 구성안을 먼저 바로잡아주세요.",
    );
    expect(toWriteBlockedReason({ ...WRITABLE, order: "waiting" })).toBe("앞 화 원고를 먼저 써주세요.");
    expect(toWriteBlockedReason({ ...WRITABLE, order: "laterWritten" })).toBe("뒤 화에 원고가 있어 이 화는 쓸 수 없어요.");
    expect(toWriteBlockedReason({ ...WRITABLE, hasApproved: false })).toBe("장면 구성안을 승인하면 원고를 쓸 수 있어요.");
    expect(toWriteBlockedReason({ ...WRITABLE, hasNewerDraft: true })).toBe(
      "승인하지 않은 새 장면 구성안이 있어요. 승인한 뒤 원고를 쓸 수 있어요.",
    );
    expect(toWriteBlockedReason({ ...WRITABLE, isApprovedStale: true })).toBe(
      "장면 구성안이 낡았어요. 다시 만들어 승인한 뒤 원고를 쓸 수 있어요.",
    );
    expect(toWriteBlockedReason({ ...WRITABLE, isDirty: true })).toBe("고친 장면 구성안을 먼저 저장하고 승인해주세요.");
  });

  it("순서가 승인보다 먼저다(앞 화를 써야 풀리는 쪽)", () => {
    expect(toWriteBlockedReason({ ...WRITABLE, order: "waiting", hasApproved: false })).toBe("앞 화 원고를 먼저 써주세요.");
  });
});
