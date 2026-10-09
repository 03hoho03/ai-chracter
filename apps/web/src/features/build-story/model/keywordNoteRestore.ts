import { MAX_ALWAYS_ON_KEYWORD_NOTES, MAX_KEYWORD_NOTES, type KeywordNoteValues } from "./schema";

/**
 * 지운 키워드 노트를 되돌릴지의 판정(반복 항목 공용 되돌리기의 `decideRestore` 모양). 그 사이 노트를 더 만들었으면 되살린
 * 노트까지 서버 상한을 넘을 수 있다 — 자동저장은 발행 검사를 거치지 않아 넘은 목록이 폼에 들어가면 서버가 초안 저장을 통째로
 * 거절한다.
 *
 * - 노트가 이미 `MAX_KEYWORD_NOTES` 개면 되살리지 않는다.
 * - 상시 노트가 이미 `MAX_ALWAYS_ON_KEYWORD_NOTES` 개인데 되살릴 노트도 상시면, 상시를 끈 채 되살리고 그 사실을 알린다 —
 *   노트 내용은 남기는 편이 통째로 거절하는 것보다 잃는 것이 적다.
 */
export function keywordNoteRestoreDecision(
  notes: readonly Pick<KeywordNoteValues, "alwaysOn">[],
  note: KeywordNoteValues,
):
  | { kind: "restore"; item: KeywordNoteValues; note?: string }
  | { kind: "refuse"; reason: string } {
  if (notes.length >= MAX_KEYWORD_NOTES) {
    return { kind: "refuse", reason: `노트는 최대 ${MAX_KEYWORD_NOTES}개까지예요.` };
  }
  const alwaysOnCount = notes.filter((each) => each.alwaysOn).length;
  if (note.alwaysOn && alwaysOnCount >= MAX_ALWAYS_ON_KEYWORD_NOTES) {
    return {
      kind: "restore",
      item: { ...note, alwaysOn: false },
      note: `상시 노트는 최대 ${MAX_ALWAYS_ON_KEYWORD_NOTES}개라 상시를 끄고 되살렸어요.`,
    };
  }
  return { kind: "restore", item: note };
}
