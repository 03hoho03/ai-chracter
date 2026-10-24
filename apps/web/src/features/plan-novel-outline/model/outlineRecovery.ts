import { hasNovelErrorCode } from "@/entities/novel";
import { isApiError } from "@/shared/api/client";

/** 구성안 저장·승인이 거절된 뒤 화면을 서버와 맞추는 일. 문구는 `toNovelActionError` 가 따로 정한다. */
export type OutlineRecovery = {
  /** 이 화면이 고친 것을 버린다 — 그 고침이 낡은 판이나 지금 대화와 어긋난 메시지 위에 있다. */
  resetEdits: boolean;
  refetchOutline: boolean;
  refetchMessages: boolean;
  /** 스위치를 다시 받는다 — 꺼졌으면 구성 화면이 거둬진다. */
  refetchPricing: boolean;
};

const NOTHING: OutlineRecovery = { resetEdits: false, refetchOutline: false, refetchMessages: false, refetchPricing: false };

/** 고친 것을 남겨 두고 이용자가 고쳐 다시 저장하는 편집 검증 이유. 화 수는 이용자가 줄이면 되고, 겹침·턴 가르기는 화면 계산이
 * 서버와 어긋난 경우라 다시 받아도 같은 판이 온다. 나머지 이유(키·근거가 서버 판과 어긋남)는 다시 받아야 풀린다. */
const KEEP_EDIT_REASONS = new Set(["too_many_episodes", "basis_overlap", "basis_splits_turn"]);

export function toOutlineRecovery(error: unknown): OutlineRecovery {
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_CONFLICT") || hasNovelErrorCode(error, "NOVEL_OUTLINE_STALE")) {
    return { ...NOTHING, resetEdits: true, refetchOutline: true };
  }
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_INVALID")) {
    const reason = reasonOf(error);
    if (reason !== undefined && KEEP_EDIT_REASONS.has(reason)) return NOTHING;
    return { ...NOTHING, resetEdits: true, refetchOutline: true, refetchMessages: reason === "basis_not_found" };
  }
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_FLOW_DISABLED")) return { ...NOTHING, refetchPricing: true };
  return NOTHING;
}

function reasonOf(error: unknown): string | undefined {
  if (!isApiError(error)) return undefined;
  const { detail } = error;
  if (!detail || typeof detail !== "object" || !("reason" in detail)) return undefined;
  return typeof detail.reason === "string" ? detail.reason : undefined;
}
