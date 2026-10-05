import type { NovelRevisionSummary } from "../api/useNovelRevisionsQuery";

/** 판이 어떻게 생겼는지 한 마디로. 되돌린 판은 어느 판에서 왔는지까지 말한다 — 목록에서 그 판을 찾으면 번호로,
 * 못 찾으면(목록 밖) 번호 없이. */
export function toRevisionSourceLabel(
  revision: Pick<NovelRevisionSummary, "source" | "revertedFromRevisionId">,
  revisions: readonly Pick<NovelRevisionSummary, "id" | "revisionNo">[],
): string {
  switch (revision.source) {
    case "generate":
      return "처음 만듦";
    case "regenerate":
      return "다시 만듦";
    case "manual_edit":
      return "직접 고침";
    case "ai_edit":
      return "AI로 고침";
    case "revert": {
      const from = revisions.find((item) => item.id === revision.revertedFromRevisionId);
      return from === undefined ? "옛 판으로 되돌림" : `${from.revisionNo}판으로 되돌림`;
    }
  }
}
