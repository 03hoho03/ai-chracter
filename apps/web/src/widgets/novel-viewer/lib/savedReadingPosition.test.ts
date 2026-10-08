import { describe, expect, it } from "vitest";

import type { NovelDetailResponse } from "@/entities/novel";

import { toChapterSavedReadingPosition } from "./savedReadingPosition";

const position = {
  paragraphIndex: 7,
  paragraphCount: 20,
  revisionId: "r3",
  finished: false,
  updatedAt: "2026-10-08T00:00:00Z",
};

const lastRead: NonNullable<NovelDetailResponse["lastRead"]> = {
  chapterId: "c3",
  revisionId: "r3",
  paragraphIndex: 12,
  paragraphCount: 20,
  updatedAt: "2026-10-08T00:00:00Z",
};

describe("toChapterSavedReadingPosition", () => {
  it("화 요약에 실린 그 화의 자리를 쓴다(마지막 읽은 화가 아니어도)", () => {
    expect(toChapterSavedReadingPosition({ id: "c5", readingPosition: position }, lastRead)).toEqual({
      saved: position,
      isAbsenceKnown: true,
    });
  });

  it("읽은 적 없는 화는 자리 없음이 확실하다", () => {
    expect(toChapterSavedReadingPosition({ id: "c5", readingPosition: null }, lastRead)).toEqual({
      saved: undefined,
      isAbsenceKnown: true,
    });
  });

  // 화별 읽은 자리를 싣기 전의 API 가 준 화 요약에는 `readingPosition` 칸이 없다.
  it("칸이 없는 옛 응답이면 마지막 읽은 화일 때만 그 자리로 연다", () => {
    expect(toChapterSavedReadingPosition({ id: "c3" }, lastRead)).toEqual({ saved: lastRead, isAbsenceKnown: true });
  });

  it("칸이 없는 옛 응답의 다른 화는 자리를 모른다 — 서버 자리를 덮지 않게", () => {
    expect(toChapterSavedReadingPosition({ id: "c5" }, lastRead)).toEqual({ saved: undefined, isAbsenceKnown: false });
    expect(toChapterSavedReadingPosition({ id: "c5" }, null)).toEqual({ saved: undefined, isAbsenceKnown: false });
  });
});
