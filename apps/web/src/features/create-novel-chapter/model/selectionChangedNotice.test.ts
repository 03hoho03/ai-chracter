import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import {
  isSelectionChangedFailure,
  isSelectionChangedRefusal,
  shouldReturnToSelection,
  withoutSelectionChangedNotice,
} from "./selectionChangedNotice";

function apiError(status: number, code: string) {
  return new ApiErrorObject({ status, message: "x", detail: { code } });
}

const CHANGED = apiError(409, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED");

describe("담을 대화 원문이 바뀌어 거절된 요청", () => {
  it("원문 바뀜 409 만 담을 대화 탓이다", () => {
    expect(isSelectionChangedRefusal(CHANGED)).toBe(true);
    expect(isSelectionChangedRefusal(apiError(409, "NOVEL_SOURCE_CHANGED"))).toBe(false);
    expect(isSelectionChangedRefusal(apiError(409, "NOVEL_OUTLINE_STALE"))).toBe(false);
  });

  // 화 화면에는 표시한 구간도 담을 대화로 가는 길도 없다 — 거기서 받은 거절은 담을 대화가 있는 구성 문서로 돌아가야 풀린다. 전체 구성안은
  // 이미 그 문서 안이라 옮기지 않는다.
  it("장면 구성안·원고 요청이 그 거절을 받았을 때만 담을 대화로 돌아간다", () => {
    expect(shouldReturnToSelection(CHANGED, "episodeOutline")).toBe(true);
    expect(shouldReturnToSelection(CHANGED, "outlineChapter")).toBe(true);
    expect(shouldReturnToSelection(CHANGED, "outline")).toBe(false);
    expect(shouldReturnToSelection(apiError(409, "NOVEL_OUTLINE_STALE"), "episodeOutline")).toBe(false);
  });
});

describe("담을 대화 원문이 바뀌어 실패한 작업", () => {
  it("구성 흐름 세 작업의 원문 바뀜 실패만이다", () => {
    for (const kind of ["outline_generate", "episode_outline_generate", "outline_chapter_generate"] as const) {
      expect(isSelectionChangedFailure({ kind, failureReason: "source_changed" })).toBe(true);
      expect(isSelectionChangedFailure({ kind, failureReason: "malformed" })).toBe(false);
    }
    // 옛 화 만들기의 원문 바뀜은 담을 대화를 다시 승인해도 풀리지 않는다.
    expect(isSelectionChangedFailure({ kind: "chapter_regenerate", failureReason: "source_changed" })).toBe(false);
  });
});

describe("담을 대화를 다시 승인한 뒤의 작업 줄 안내", () => {
  it("담을 대화 탓의 오류만 지우고 다른 안내는 남긴다", () => {
    expect(
      withoutSelectionChangedNotice({ tone: "error", message: "바뀜", isSelectionChanged: true }),
    ).toBeUndefined();
    const other = { tone: "error" as const, message: "잔액 부족" };
    expect(withoutSelectionChangedNotice(other)).toBe(other);
    const done = { tone: "done" as const, message: "다 썼어요" };
    expect(withoutSelectionChangedNotice(done)).toBe(done);
    expect(withoutSelectionChangedNotice(undefined)).toBeUndefined();
  });
});
