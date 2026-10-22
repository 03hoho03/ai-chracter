import type { NovelRevisionSummary } from "../api/useNovelRevisionsQuery";

/** 펼친 판 미리보기의 보기 — 이 판 글, 바로 앞 판과 비교, 지금 글과 비교. */
export type RevisionPreviewMode = "text" | "previous" | "current";

/** 판을 펼쳤을 때 처음 보기. 그 판이 무엇을 바꿨는지가 먼저라 앞 판과 비교이고, 첫 판이면(앞 판이 없다) 지금 글과
 * 비교, 그것도 없으면(판이 하나뿐) 글 그대로다. 삽화를 바꾼 판은 글이 앞 판과 같아 글 비교가 할 말이 없으니 그 판 글(그림
 * 포함)부터 보인다. */
export function toInitialPreviewMode({
  source,
  hasPrevious,
  hasCurrent,
}: {
  source: NovelRevisionSummary["source"];
  hasPrevious: boolean;
  hasCurrent: boolean;
}): RevisionPreviewMode {
  if (source === "illustration") return "text";
  if (hasPrevious) return "previous";
  if (hasCurrent) return "current";
  return "text";
}
