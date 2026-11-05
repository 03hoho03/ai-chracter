import { hasNovelErrorCode } from "@/entities/novel";
import { isApiError } from "@/shared/api/client";

/** 장면 구성안 저장·승인이 거절된 뒤 화면을 서버와 맞추는 일. 문구는 `toNovelActionError` 가 따로 정한다. */
export type EpisodeOutlineRecovery = {
  /** 이 화면이 고친 것을 버린다 — 그 고침이 낡은 판이나 지금 대화와 어긋난 판 위에 있다. */
  shouldResetEdits: boolean;
  shouldRefetchEpisode: boolean;
  /** 전체 구성안을 다시 받는다 — 화 목록의 장면 구성안 상태·낡음이 바뀌었다. */
  shouldRefetchOutline: boolean;
  shouldRefetchMessages: boolean;
  /** 스위치를 다시 받는다 — 꺼졌으면 구성 화면이 거둬진다. */
  shouldRefetchPricing: boolean;
};

const NOTHING: EpisodeOutlineRecovery = {
  shouldResetEdits: false,
  shouldRefetchEpisode: false,
  shouldRefetchOutline: false,
  shouldRefetchMessages: false,
  shouldRefetchPricing: false,
};

/** 이 화면은 장면 근거를 고치지 않으므로 편집 검증 거절(`NOVEL_EPISODE_OUTLINE_INVALID`)은 어느 이유든 서버 판이나 대화가 그사이 바뀐
 * 것이다 — 남겨 둬도 다시 저장하면 같은 거절이라, 버리고 다시 받는다. */
export function toEpisodeOutlineRecovery(error: unknown): EpisodeOutlineRecovery {
  if (hasNovelErrorCode(error, "NOVEL_EPISODE_OUTLINE_CONFLICT")) return { ...NOTHING, shouldResetEdits: true, shouldRefetchEpisode: true };
  if (hasNovelErrorCode(error, "NOVEL_EPISODE_OUTLINE_STALE")) {
    return { ...NOTHING, shouldResetEdits: true, shouldRefetchEpisode: true, shouldRefetchOutline: true };
  }
  if (hasNovelErrorCode(error, "NOVEL_EPISODE_OUTLINE_INVALID")) {
    return { ...NOTHING, shouldResetEdits: true, shouldRefetchEpisode: true, shouldRefetchMessages: isBasisNotFound(error) };
  }
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_REQUIRED") || hasNovelErrorCode(error, "NOVEL_OUTLINE_EPISODE_NOT_FOUND")) {
    return { ...NOTHING, shouldResetEdits: true, shouldRefetchEpisode: true, shouldRefetchOutline: true };
  }
  if (hasNovelErrorCode(error, "NOVEL_OUTLINE_FLOW_DISABLED")) return { ...NOTHING, shouldRefetchPricing: true };
  return NOTHING;
}

function isBasisNotFound(error: unknown): boolean {
  if (!isApiError(error)) return false;
  const { detail } = error;
  return typeof detail === "object" && detail !== null && "reason" in detail && detail.reason === "basis_not_found";
}
