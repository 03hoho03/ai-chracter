import type { NovelSourceSelectionState, NovelSourceSelectionView } from "@/entities/novel";

/** 담을 대화 단계의 상태. 저장 전(서버의 기본 제안뿐) · 초안(승인하지 않은 최신 판) · 승인됨(최신 판이 승인본). */
export type SourceSelectionStatus = "unsaved" | "draft" | "approved";

export const SOURCE_SELECTION_STATUS_LABEL: Record<SourceSelectionStatus, string> = {
  unsaved: "저장 전",
  draft: "초안",
  approved: "승인됨",
};

export function toSourceSelectionStatus(state: NovelSourceSelectionState): SourceSelectionStatus {
  if (state.draft !== null) return "draft";
  if (state.approved !== null) return "approved";
  return "unsaved";
}

/** 화면이 보여 주고 고치기 시작할 판과, 저장할 때 보낼 기준 리비전(그 소설의 최신 판 — 없으면 null). 초안은 늘 승인본보다
 * 새 판이라 초안이 먼저다. 셋 다 없으면 받은 응답이 어긋난 것이라 판이 없다. */
export function toSourceSelectionBase(
  state: NovelSourceSelectionState,
): { view: NovelSourceSelectionView; baseRevision: number | null } | undefined {
  const view = state.draft ?? state.approved ?? state.proposal;
  if (view === null) return undefined;
  return { view, baseRevision: (state.draft ?? state.approved)?.revision ?? null };
}

/** 저장한 뒤 원문이 바뀐 구간이 있는가. 있으면 승인 전에 지금 원문으로 다시 저장해야 한다. */
export function hasChangedSource(view: NovelSourceSelectionView): boolean {
  return view.sections.some((section) => section.sourceChanged);
}
