import { describe, expect, it } from "vitest";

import { keywordNoteRestoreDecision } from "./keywordNoteRestore";
import { createKeywordNote, MAX_ALWAYS_ON_KEYWORD_NOTES, MAX_KEYWORD_NOTES } from "./schema";

function notes(count: number, alwaysOnCount = 0) {
  return Array.from({ length: count }, (_, index) => ({ alwaysOn: index < alwaysOnCount }));
}

const plain = createKeywordNote("n");
const alwaysOn = { ...createKeywordNote("a"), alwaysOn: true };

describe("keywordNoteRestoreDecision", () => {
  it("상한 아래면 그대로 되살린다", () => {
    expect(keywordNoteRestoreDecision(notes(MAX_KEYWORD_NOTES - 1), plain)).toEqual({ kind: "restore", item: plain });
  });

  it("노트가 이미 상한이면 되살리지 않는다", () => {
    expect(keywordNoteRestoreDecision(notes(MAX_KEYWORD_NOTES), plain).kind).toBe("refuse");
  });

  it("상시가 꽉 찼으면 상시 노트는 상시를 끄고 되살리고 그 사실을 알린다", () => {
    const decision = keywordNoteRestoreDecision(notes(5, MAX_ALWAYS_ON_KEYWORD_NOTES), alwaysOn);
    expect(decision).toEqual({
      kind: "restore",
      item: { ...alwaysOn, alwaysOn: false },
      note: expect.stringContaining("상시를 끄고") as unknown,
    });
  });

  it("상시가 한 자리 남았으면 상시 그대로 되살린다", () => {
    const decision = keywordNoteRestoreDecision(notes(5, MAX_ALWAYS_ON_KEYWORD_NOTES - 1), alwaysOn);
    expect(decision).toEqual({ kind: "restore", item: alwaysOn });
  });

  it("상시가 꽉 차도 상시가 아닌 노트는 그대로 되살린다", () => {
    expect(keywordNoteRestoreDecision(notes(5, MAX_ALWAYS_ON_KEYWORD_NOTES), plain)).toEqual({
      kind: "restore",
      item: plain,
    });
  });

  it("노트 상한이 상시 상한보다 먼저다 — 둘 다 걸리면 되살리지 않는다", () => {
    expect(keywordNoteRestoreDecision(notes(MAX_KEYWORD_NOTES, MAX_ALWAYS_ON_KEYWORD_NOTES), alwaysOn).kind).toBe("refuse");
  });
});
