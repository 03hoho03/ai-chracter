import type { NovelSourceSelectionState, NovelSourceSelectionView } from "@/entities/novel";

import { canPlaceByKey, type SourceMessage } from "./sourceTimeline";

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

/** 구성안 다음 단계(장면 구성안·원고)가 쓰는 승인한 판의 상태 — 승인본이 없으면 `unapproved`, 승인본의 구간 하나라도 원문이 바뀌었으면
 * `sourceChanged`(서버는 그중 맥락 구간이나 그 화의 근거가 든 구간이 바뀌었을 때 그 단계의 과금 요청을 409 로 막는다), 아니면 `ok`.
 * 승인본 위의 새 초안은 보지 않는다: 그 단계는 승인본으로 만들고, 원문 바뀜을 고쳐 저장한 초안도 승인해야 풀린다. */
export function toApprovedSourceStatus(state: NovelSourceSelectionState): "ok" | "sourceChanged" | "unapproved" {
  if (state.approved === null) return "unapproved";
  return hasChangedSource(state.approved) ? "sourceChanged" : "ok";
}

/** 고른 때의 고정 끝을 지금 대화에서 자리 잡을 수 없는가. 그 메시지가 지워졌어도 키(`roomEndMessageCreatedAt`)로 자리를 잡을 수
 * 있으면 잃은 것이 아니다 — 그 키까지가 고른 대화이고 뒤는 새 대화라, 저장은 지워진 고정 끝 id 그대로 보내도 서버가 받는다(확장하지
 * 않은 저장은 최신 판의 고정 끝 id 와 같은지만 본다). 키를 모를 때(서버가 그 칸을 싣기 전 응답)만 잃는다. */
export function isFixedEndLost(
  messages: readonly SourceMessage[],
  view: { roomEndMessageId: string | null; roomEndMessageCreatedAt?: string | null },
): boolean {
  const fixedEndId = view.roomEndMessageId;
  if (fixedEndId === null || messages.some((message) => message.id === fixedEndId)) return false;
  return !canPlaceByKey(messages, view.roomEndMessageCreatedAt, fixedEndId);
}

/** 저장할 때 보낼 고정 끝. 새 구간을 열었으면 화면이 본 지금 방 끝으로 옮긴다(`extendToRoomEnd`). 고른 때의 고정 끝을 잃었으면
 * (`isFixedEndLost` — 지워졌고 키도 모른다) 화면은 어디까지가 그 선택의 대화인지 가를 수 없다 — 그대로 보내면 서버가 저장해 둔
 * 끝보다 뒤에 쓰인 메시지를 담은 구간을 범위 밖이라 거절해 같은 거절이 되풀이되므로, 이때도 지금 방 끝으로 옮긴다. 화면은 이때 안내
 * 한 줄로 담기·빼기를 확인하게 한다. */
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
