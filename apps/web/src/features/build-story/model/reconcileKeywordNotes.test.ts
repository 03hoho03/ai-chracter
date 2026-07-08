import { describe, expect, it } from "vitest";

import { reconcileKeywordNotesOnStartingSetupRemoval } from "./reconcileKeywordNotes";
import type { KeywordNoteValues } from "./schema";

function globalNote(id: string): KeywordNoteValues {
  return { id, content: "글로벌 노트", triggerKeywords: ["항상"], scope: { kind: "global" } };
}

function scopedNote(id: string, startingSetupId: string): KeywordNoteValues {
  return {
    id,
    content: "설정 전용 노트",
    triggerKeywords: ["밤"],
    scope: { kind: "startingSetup", startingSetupId },
  };
}

describe("reconcileKeywordNotesOnStartingSetupRemoval", () => {
  it("converts a note scoped to the removed starting setup into a global note", () => {
    const result = reconcileKeywordNotesOnStartingSetupRemoval([scopedNote("note-1", "setup-1")], "setup-1");

    expect(result).toEqual([{ id: "note-1", content: "설정 전용 노트", triggerKeywords: ["밤"], scope: { kind: "global" } }]);
  });

  it("leaves notes scoped to a different starting setup untouched", () => {
    const untouched = scopedNote("note-2", "setup-2");

    const result = reconcileKeywordNotesOnStartingSetupRemoval([untouched], "setup-1");

    expect(result).toEqual([untouched]);
  });

  it("leaves already-global notes untouched", () => {
    const note = globalNote("note-3");

    const result = reconcileKeywordNotesOnStartingSetupRemoval([note], "setup-1");

    expect(result).toEqual([note]);
  });
});
