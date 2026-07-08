import type { KeywordNoteValues } from "./schema";

/**
 * techspec-builder-story.md §1.3 — 시작설정 삭제 시 그 시작설정을 참조하던 키워드 노트를 삭제하지
 * 않고 global 스코프로 전환해 보존한다("정리(또는 경고 후 global로 전환)" 중 데이터 손실이 없는
 * 후자를 채택). 시작설정 삭제 UI(향후 스토리)는 배열에서 항목을 제거하기 전에 이 함수를 호출한다.
 */
export function reconcileKeywordNotesOnStartingSetupRemoval(
  keywordNotes: KeywordNoteValues[],
  removedStartingSetupId: string,
): KeywordNoteValues[] {
  return keywordNotes.map((note) =>
    note.scope.kind === "startingSetup" && note.scope.startingSetupId === removedStartingSetupId
      ? { ...note, scope: { kind: "global" } }
      : note,
  );
}
