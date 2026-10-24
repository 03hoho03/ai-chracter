import { hasNovelErrorCode } from "@/entities/novel";

/** 저장·승인이 거절된 뒤 화면을 서버와 맞추는 일. 문구는 `toNovelActionError` 가 따로 정한다. */
export type SelectionRecovery = {
  /** 이 화면이 고친 것을 버린다 — 그 고침이 낡은 판이나 지금 대화와 어긋난 메시지 위에 있다. */
  resetEdits: boolean;
  refetchSelection: boolean;
  refetchMessages: boolean;
  /** 스위치를 다시 받는다 — 꺼졌으면 구성 화면이 거둬진다. */
  refetchPricing: boolean;
};

const NOTHING: SelectionRecovery = {
  resetEdits: false,
  refetchSelection: false,
  refetchMessages: false,
  refetchPricing: false,
};

const MISMATCHED_CODES = [
  "NOVEL_SOURCE_MESSAGE_NOT_FOUND",
  "NOVEL_SOURCE_SECTION_INVALID",
  "NOVEL_SOURCE_SECTION_OUT_OF_RANGE",
] as const;

export function toSelectionRecovery(error: unknown): SelectionRecovery {
  if (hasNovelErrorCode(error, "NOVEL_SOURCE_SELECTION_CONFLICT")) {
    return { ...NOTHING, resetEdits: true, refetchSelection: true };
  }
  // 초안은 서버에 그대로다. 다시 받으면 바뀐 구간 표시가 오고, 다시 승인하면 지금 원문으로 저장한 뒤 승인한다.
  if (hasNovelErrorCode(error, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED")) {
    return { ...NOTHING, refetchSelection: true, refetchMessages: true };
  }
  if (MISMATCHED_CODES.some((code) => hasNovelErrorCode(error, code))) {
    return { ...NOTHING, resetEdits: true, refetchSelection: true, refetchMessages: true };
  }
  // 그사이 화가 생겼다. 새 잠금을 받으면 잠긴 턴은 화면이 담기로 보내지 않으므로 고친 것은 둔다.
  if (hasNovelErrorCode(error, "NOVEL_SOURCE_SECTION_LOCKED")) return { ...NOTHING, refetchSelection: true };
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_FLOW_DISABLED")) return { ...NOTHING, refetchPricing: true };
  return NOTHING;
}
