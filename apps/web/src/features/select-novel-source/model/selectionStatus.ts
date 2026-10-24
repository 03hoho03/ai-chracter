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

/** 저장할 때 보낼 고정 끝. 새 구간을 열었으면 화면이 본 지금 방 끝으로 옮긴다(`extendToRoomEnd`). 고른 때의 고정 끝 메시지를
 * 지금 대화에서 찾지 못하면(마지막 답을 다시 만들었거나 지웠다) 화면은 어디까지가 그 선택의 대화인지 가를 수 없다 — 그대로
 * 보내면 서버가 저장해 둔 끝보다 뒤에 쓰인 메시지를 담은 구간을 범위 밖이라 거절해 같은 거절이 되풀이되므로, 이때도 지금 방
 * 끝으로 옮긴다. 그 뒤 대화는 어느 구간에도 들지 않아 빼기로 보이므로, 이용자가 담지 않은 대화가 저절로 담기지는 않는다. */
export function toSaveRoomEnd(options: {
  isExtended: boolean;
  isFixedEndMissing: boolean;
  fixedEndId: string;
  roomEndId: string;
}): { roomEndMessageId: string; extendToRoomEnd: boolean } {
  if (options.isExtended || options.isFixedEndMissing) {
    return { roomEndMessageId: options.roomEndId, extendToRoomEnd: true };
  }
  return { roomEndMessageId: options.fixedEndId, extendToRoomEnd: false };
}
