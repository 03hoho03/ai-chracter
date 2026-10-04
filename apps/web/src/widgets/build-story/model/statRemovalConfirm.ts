import type { StatRemovalCounts } from "@/features/build-story";

/**
 * 스탯 삭제 확인 모달의 설명 — 함께 지워지는 엔딩·상황 노트 조건을 한 문장으로 센다. 엔딩 조건만 걸린 경우는 상황 노트가
 * 생기기 전과 같은 문장이다. 조건이 모두 사라지는 노트가 있으면 한 문장을 더한다 — 엔딩은 조건이 없어도 판단 프롬프트로
 * 판정되지만 상황 노트는 조건이 없으면 발행이 막히고 대화에도 실리지 않아, 작가가 확정 전에 알아야 한다.
 */
export function statRemovalConfirmDescription({
  endingRuleCount,
  noteRuleCount,
  emptiedNoteCount,
}: StatRemovalCounts): string {
  const endingPart = endingRuleCount > 0 ? `엔딩 조건 ${endingRuleCount}개` : undefined;
  const notePart = noteRuleCount > 0 ? `상황 노트 조건 ${noteRuleCount}개` : undefined;
  const subject = endingPart && notePart ? `${endingPart}와 ${notePart}` : (endingPart ?? notePart);
  const removal = `이 스탯을 쓰는 ${subject}도 함께 지워져요.`;
  if (emptiedNoteCount === 0) return removal;
  return `${removal} 조건이 모두 사라지는 상황 노트 ${emptiedNoteCount}개는 조건을 다시 넣어야 발행할 수 있어요.`;
}
