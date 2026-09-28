import { describe, expect, it } from "vitest";

import type { ChatRoomMemory } from "@/entities/chat-room";

import { toNoteRequest, toSummaryRequest } from "./formToServer";
import { serverToForm } from "./serverToForm";

function memory(overrides: Partial<ChatRoomMemory> = {}): ChatRoomMemory {
  return {
    note: "주인공은 고양이를 무서워한다",
    summary: { text: "둘은 비 오는 밤 처음 만났다.", source: "auto", canRevert: false, updatedAt: "2026-09-28T00:00:00Z" },
    version: 3,
    limits: { noteMaxLength: 1000, summaryMaxLength: 1500 },
    ...overrides,
  };
}

describe("serverToForm", () => {
  it("fills both fields from the response", () => {
    expect(serverToForm(memory())).toEqual({
      note: "주인공은 고양이를 무서워한다",
      summary: "둘은 비 오는 밤 처음 만났다.",
    });
  });

  it("leaves the summary field empty before the first summary exists", () => {
    expect(serverToForm(memory({ summary: undefined })).summary).toBe("");
  });
});

describe("formToServer", () => {
  const values = { note: "노트", summary: "요약" };

  // 노트 저장이 요약 칸을 함께 보내면 서버 스키마가 모르는 필드를 싣게 된다 — 칸마다 저장 경로가 따로다.
  it("sends only the note to the note route", () => {
    expect(toNoteRequest(values)).toEqual({ note: "노트" });
  });

  it("sends the summary with the version the form was opened at", () => {
    expect(toSummaryRequest(values, 3)).toEqual({ summary: "요약", version: 3 });
  });

  it("round-trips a response through the form unchanged", () => {
    const form = serverToForm(memory());
    expect(toNoteRequest(form).note).toBe(memory().note);
    expect(toSummaryRequest(form, memory().version)).toEqual({
      summary: "둘은 비 오는 밤 처음 만났다.",
      version: 3,
    });
  });
});
