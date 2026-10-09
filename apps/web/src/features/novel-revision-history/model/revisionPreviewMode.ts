/** 펼친 판 미리보기의 보기 — 이 판 글, 바로 앞 판과 비교, 지금 글과 비교. */
export type RevisionPreviewMode = "text" | "previous" | "current";

/** 판을 펼쳤을 때 처음 보기. 그 판이 무엇을 바꿨는지가 먼저라 앞 판과 비교이고, 첫 판이면(앞 판이 없다) 지금 글과
 * 비교, 그것도 없으면(판이 하나뿐) 글 그대로다. */
export function toInitialPreviewMode({
  hasPrevious,
  hasCurrent,
}: {
  hasPrevious: boolean;
  hasCurrent: boolean;
}): RevisionPreviewMode {
  if (hasPrevious) return "previous";
  if (hasCurrent) return "current";
  return "text";
}
