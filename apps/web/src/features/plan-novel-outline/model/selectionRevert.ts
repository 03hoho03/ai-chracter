import type { NovelOutlineView } from "@/entities/novel";

import type { OutlineRange } from "./outlineEdits";

/**
 * 낡은 구성안의 "구간 되돌리기"가 담을 대화 단계에 넘길 것.
 *
 * - `exact`: 그 구성안이 쓴 선택의 담기 구간(서버가 낡은 판에 싣는다). 양 끝 그대로 되돌리면 승인한 뒤 낡음이 풀린다.
 * - `approximate`: 그 칸이 없을 때(서버가 그 칸을 싣기 전 응답) 화들의 근거로 어림한다 — 지운 화나 근거 밖 턴은 놓친다.
 * - `sourceChanged`: 구간 하나라도 원문이 바뀌었다. 되돌려도 해시가 달라 낡음이 풀리지 않으니 다시 만들어야 한다.
 */
export type SelectionRevert =
  | { kind: "exact"; ranges: OutlineRange[] }
  | { kind: "approximate"; ranges: OutlineRange[] }
  | { kind: "sourceChanged" };

export function toSelectionRevert(view: {
  episodes: readonly Pick<NovelOutlineView["episodes"][number], "basis">[];
  sourceSections?: NovelOutlineView["sourceSections"];
}): SelectionRevert {
  const sections = view.sourceSections;
  if (sections === undefined || sections === null) {
    return { kind: "approximate", ranges: view.episodes.flatMap((episode) => episode.basis) };
  }
  if (sections.some((section) => section.sourceChanged)) return { kind: "sourceChanged" };
  return { kind: "exact", ranges: sections };
}
