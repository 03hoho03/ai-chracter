import { describe, expect, it } from "vitest";

import type { NovelOutlineState, NovelOutlineView } from "@/entities/novel";

import { isEditBaseOutdated, toEpisodeOrdinals, toMakeBlockedReason, toOutlineBase } from "./outlineStatus";

function view(revision: number, extra: Partial<NovelOutlineView> = {}): NovelOutlineView {
  return {
    revision,
    source: "generate",
    model: "gemini",
    approvedAt: null,
    createdAt: "2026-10-24T00:00:00Z",
    stale: false,
    episodes: [],
    ...extra,
  };
}

function state(approved: NovelOutlineView | null, draft: NovelOutlineView | null): NovelOutlineState {
  return { approved, draft, maxEpisodes: 30, models: [] };
}

describe("구성안 상태", () => {
  it("판이 없으면 비었다", () => {
    expect(toOutlineBase(state(null, null))).toBeUndefined();
  });

  it("초안이 승인본보다 먼저다(늘 더 새 판이다)", () => {
    const approved = view(1, { approvedAt: "2026-10-24T01:00:00Z" });
    const draft = view(2);
    expect(toOutlineBase(state(approved, draft))).toEqual({ view: draft, status: "draft", isStale: false });
    expect(toOutlineBase(state(approved, null))).toEqual({ view: approved, status: "approved", isStale: false });
  });

  it("보이는 판이 낡았으면 낡음이다", () => {
    expect(toOutlineBase(state(null, view(2, { stale: true })))?.isStale).toBe(true);
  });
});

describe("구성안 만들기를 못 누르는 이유", () => {
  const idle = {
    isRoomGone: false,
    isJobRunning: false,
    isAiEditRunning: false,
    hasApprovedSelection: true,
    isDirty: false,
  };

  it("막을 것이 없으면 이유가 없다", () => {
    expect(toMakeBlockedReason(idle)).toBeUndefined();
  });

  it("방 없음이 가장 먼저고, 그다음 진행 중 작업·AI 수정·승인한 대화 없음·고친 구성안 순이다", () => {
    expect(toMakeBlockedReason({ ...idle, isRoomGone: true, isJobRunning: true })).toBe(
      "원래 대화방이 지워져 구성안을 새로 만들 수 없어요.",
    );
    expect(toMakeBlockedReason({ ...idle, isJobRunning: true, isAiEditRunning: true, isDirty: true })).toBe(
      "다른 작업이 끝나면 만들 수 있어요.",
    );
    expect(toMakeBlockedReason({ ...idle, isAiEditRunning: true, hasApprovedSelection: false })).toBe(
      "AI로 고치는 중이에요. 끝나면 만들 수 있어요.",
    );
    expect(toMakeBlockedReason({ ...idle, hasApprovedSelection: false, isDirty: true })).toBe(
      "담을 대화를 먼저 승인해주세요.",
    );
    expect(toMakeBlockedReason({ ...idle, isDirty: true })).toBe("고친 구성안을 먼저 저장하거나 되돌려주세요.");
    expect(toMakeBlockedReason({ ...idle, hasApprovedSelection: undefined })).toBe("담을 대화를 확인하는 중이에요.");
  });
});

describe("고침이 새 판 앞에서 낡았나", () => {
  it("고치기 시작한 판보다 새 판이 오면 낡았다", () => {
    expect(isEditBaseOutdated(2, 3)).toBe(true);
    expect(isEditBaseOutdated(2, 2)).toBe(false);
    expect(isEditBaseOutdated(undefined, 3)).toBe(false);
  });
});

describe("구성안 화 번호", () => {
  it("원고가 있는 화는 그 화 번호, 나머지는 구성안 밖 마지막 화 다음부터 차례다", () => {
    const chapters = [
      { id: "c1", ordinal: 1 },
      { id: "c2", ordinal: 2 },
      { id: "c3", ordinal: 3 },
    ];
    expect(toEpisodeOrdinals([{ chapterId: "c3" }, { chapterId: null }, { chapterId: null }], chapters)).toEqual([3, 4, 5]);
    expect(toEpisodeOrdinals([{ chapterId: null }, { chapterId: null }], [])).toEqual([1, 2]);
  });
});
