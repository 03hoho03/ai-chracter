import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

import type { NovelJobResponse } from "../api/useNovelJobQuery";

/** 오류를 받은 요청이 무엇이었나. 같은 코드라도 요청에 따라 문장이 갈리는 자리가 있다 — 시간당 상한과 하루
 * 상한이 같은 429 로 오고, 이용 제한·일반 실패도 무엇을 못 했는지가 달라서다. */
export type NovelAction =
  | "proposal"
  | "generate"
  | "regenerate"
  | "aiEdit"
  | "applyAiEdit"
  | "dismissAiEdit"
  | "edit"
  | "restore"
  | "notes"
  | "deleteChapter"
  | "deleteNovel"
  | "protagonistName";

export type NovelActionErrorNotice = {
  message: string;
  /** 상세를 다시 받아야 화면이 맞아지는 실패인가 — 단가·진행 중 작업·장 목록·대화방 유무가 서버에서 바뀌었다는
   * 뜻이다. 진행 중 작업 409 는 다시 받은 상세의 `activeJob` 으로 폴링을 이어 간다. */
  shouldRefetchNovel: boolean;
};

const ACTION_OBJECT: Record<NovelAction, string> = {
  proposal: "다음 화를 준비하지",
  generate: "화를 만들지",
  regenerate: "화를 다시 만들지",
  aiEdit: "AI로 고치지",
  applyAiEdit: "수정안을 적용하지",
  dismissAiEdit: "수정안을 버리지",
  edit: "고친 내용을 저장하지",
  restore: "이 판으로 되돌리지",
  notes: "설정 노트를 저장하지",
  deleteChapter: "화를 지우지",
  deleteNovel: "소설을 지우지",
  protagonistName: "주인공 이름을 저장하지",
};

/** 원래 대화방이 지워져 화를 만들 수도 다시 만들 수도 없을 때의 문장. 만들기 버튼 아래 사유 문장과 두 요청의 409 가
 * 같은 문장을 쓴다 — 409 문구는 요청 종류를 보지 않아서, 만들기만 말하면 다시 만들기에서 받았을 때 틀린 말이 된다. */
export const NOVEL_ROOM_GONE_MESSAGE = "원래 대화방이 지워져 새 화를 만들거나 다시 만들 수 없어요.";

/** 코드 → 문구. 기다려도 풀리지 않는 거부는 "다시 시도"를 말하지 않고, 이용자가 할 수 있는 다음 일을 말한다. */
const MESSAGE_BY_CODE: Record<string, NovelActionErrorNotice> = {
  // 행동 중에 허용이 회수된 경우다. 상세를 다시 받으면 그 조회도 403 이라 화면이 잠김 화면으로 넘어간다.
  NOVELIZE_NOT_ALLOWED: { message: "소설로 보기를 지금 이 계정에서 쓸 수 없어요.", shouldRefetchNovel: true },
  // 고른 상위 모델을 쓸 허용이 없다(기능이 꺼졌거나 허용을 거뒀다). 상세를 다시 받으면 고를 수 있는 모델 목록이 줄어
  // 다음 확인 화면이 맞아진다.
  NOVEL_MODEL_NOT_ALLOWED: {
    message: "고른 모델을 지금 이 계정에서 쓸 수 없어요. 다른 모델을 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_NOT_FOUND: { message: "소설이 지워졌어요. 내 소설에서 다시 확인해주세요.", shouldRefetchNovel: true },
  NOVEL_FORBIDDEN: { message: "이 계정의 소설이 아니에요.", shouldRefetchNovel: true },
  NOVEL_CURSOR_INVALID: { message: "목록을 처음부터 다시 불러와주세요.", shouldRefetchNovel: false },
  NOVEL_JOB_NOT_FOUND: { message: "작업을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_CHAPTER_NOT_FOUND: { message: "이 화가 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_BATCH_NOT_FOUND: { message: "함께 만든 화들이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_NOT_FOUND: { message: "이 판을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_ROOM_GONE: { message: NOVEL_ROOM_GONE_MESSAGE, shouldRefetchNovel: true },
  NOVEL_PROTAGONIST_NAME_REQUIRED: { message: "주인공 이름을 먼저 정해주세요.", shouldRefetchNovel: true },
  NOVEL_NOTHING_NEW: {
    message: "화로 묶을 새 대화가 없어요. 대화를 더 이어 간 뒤 만들어주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_END_INVALID: {
    message: "고른 턴으로는 화를 끝낼 수 없어요. 다음 화 만들기를 다시 눌러 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_NOT_LAST: { message: "마지막 화만 지울 수 있어요.", shouldRefetchNovel: true },
  NOVEL_BATCH_NOT_LAST: { message: "마지막에 함께 만든 화들만 지울 수 있어요.", shouldRefetchNovel: true },
  NOVEL_PARAGRAPH_RANGE_INVALID: { message: "고른 문단이 바뀌었어요. 다시 골라주세요.", shouldRefetchNovel: true },
  NOVEL_JOB_NOT_APPLICABLE: { message: "이 수정안은 더 이상 적용할 수 없어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_CONFLICT: {
    message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  NOVEL_SOURCE_CHANGED: {
    message: "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.",
    shouldRefetchNovel: false,
  },
  // 다시 만들기 목록이 낡았다(그사이 허용 모델·묶음이 바뀌었다) — 상세를 다시 받으면 비활성 항목과 이유가 맞아진다.
  // 이유별 문장은 아래에서 `reason` 을 보고 고른다.
  NOVEL_MODEL_INELIGIBLE: {
    message: "고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_COVER_INVALID: { message: "고른 이미지는 표지로 쓸 수 없어요. 다른 이미지를 골라주세요.", shouldRefetchNovel: false },
  NOVEL_CHARACTER_NOT_FOUND: { message: "이 인물이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_CHARACTER_NAME_TAKEN: { message: "같은 이름의 인물이 이미 있어요. 다른 이름을 써주세요.", shouldRefetchNovel: false },
  NOVEL_CHARACTER_MERGE_SELF: { message: "같은 인물끼리는 합칠 수 없어요.", shouldRefetchNovel: false },
  NOVEL_SNAPSHOT_NOT_FOUND: { message: "이 버전이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_SNAPSHOT_LIMIT: {
    message: "이름 붙인 버전이 가득 찼어요. 쓰지 않는 버전을 지운 뒤 다시 저장해주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_BOARD_LAYOUT_TOO_LARGE: {
    message: "편집 보드 배치가 너무 커서 저장하지 못했어요. 카드 몇 개를 정리한 뒤 다시 해주세요.",
    shouldRefetchNovel: false,
  },
  NOVEL_JOB_IN_PROGRESS: {
    message: "이미 진행 중인 작업이 있어요. 끝나면 다시 해주세요.",
    shouldRefetchNovel: true,
  },
  CONTENT_RESTRICTED: {
    message: "이용이 제한된 작품이라 새로 쓰는 작업을 할 수 없어요. 지금까지 만든 화는 그대로 볼 수 있어요.",
    shouldRefetchNovel: false,
  },
};

function detailCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  const { code } = detail;
  return typeof code === "string" ? code : undefined;
}

function reasonOf(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("reason" in detail)) return undefined;
  const { reason } = detail;
  return typeof reason === "string" ? reason : undefined;
}

function currentCostOf(detail: unknown): number | undefined {
  if (!detail || typeof detail !== "object" || !("currentCost" in detail)) return undefined;
  const { currentCost } = detail;
  return typeof currentCost === "number" ? currentCost : undefined;
}

function fallback(action: NovelAction): NovelActionErrorNotice {
  return { message: `${ACTION_OBJECT[action]} 못했어요. 잠시 후 다시 시도해주세요.`, shouldRefetchNovel: false };
}

/** 소설 요청 실패 → 화면에 남길 문구. `null` 은 이 화면이 말하지 않는 실패다 — 재동의 403 은 전역 재동의
 * 모달이 맡는다.
 *
 * 429 는 코드보다 먼저 본다. 제안의 시간당 상한과 장 생성·재생성의 하루 상한이 같은 `USER_LIMIT`·같은
 * `novelize` 창으로 오고 요청으로만 갈리기 때문이다. 하루 상한은 서버가 한국 날짜로 세므로 자정을 말해도 참이다.
 * 모르는 코드(서버가 새 코드를 더했는데 여기 아직 없을 때)는 요청별 일반 문구로 접는다. */
export function toNovelActionError(error: unknown, action: NovelAction): NovelActionErrorNotice | null {
  const rateLimit = getRateLimitDetail(error);
  if (rateLimit?.window === "novelize") {
    if (rateLimit.code === "CLOVER_REQUIRED") {
      return { message: "클로버가 부족해요. 클로버를 모은 뒤 다시 해주세요.", shouldRefetchNovel: false };
    }
    if (rateLimit.code === "USER_LIMIT") {
      return action === "proposal"
        ? { message: "다음 화 준비를 너무 자주 요청했어요. 잠시 후 다시 시도해주세요.", shouldRefetchNovel: false }
        : {
            message: "같은 화를 오늘 만들 수 있는 횟수를 다 썼어요. 자정이 지나면 다시 만들 수 있어요.",
            shouldRefetchNovel: false,
          };
    }
  }

  if (!isApiError(error)) return fallback(action);
  const code = detailCode(error.detail);
  if (code === undefined) return fallback(action);
  // 재동의 403 은 전역 재동의 모달이 맡는다(같은 엔티티 밖 판정 함수를 끌어오지 않으려고 코드로 직접 본다).
  if (error.status === 403 && code === "LEGAL_RECONSENT_REQUIRED") return null;

  if (code === "NOVELIZE_PRICE_CHANGED") {
    const currentCost = currentCostOf(error.detail);
    return {
      message:
        currentCost === undefined
          ? "클로버 가격이 바뀌었어요. 바뀐 가격을 확인하고 다시 해주세요."
          : `클로버 가격이 ${currentCost.toLocaleString()}개로 바뀌었어요. 바뀐 가격을 확인하고 다시 해주세요.`,
      shouldRefetchNovel: true,
    };
  }
  if (code === "NOVEL_MODEL_INELIGIBLE") {
    const reason = reasonOf(error.detail);
    if (reason === "too_many_turns") {
      return { message: "대화가 길어 고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.", shouldRefetchNovel: true };
    }
    if (reason === "too_many_episodes") {
      return { message: "화가 많아 고른 모델로는 이 화들을 다시 만들 수 없어요. 다른 모델을 골라주세요.", shouldRefetchNovel: true };
    }
  }
  return MESSAGE_BY_CODE[code] ?? fallback(action);
}

/** 서버가 재시도 전에 주인공 이름을 먼저 받으라고 한 422 인가. 상세의 이름이 낡았을 때(다른 탭이 비웠거나 첫
 * 조회 뒤 바뀌었을 때) 장 만들기 흐름이 이름 입력으로 돌아가는 신호다. */
export function isProtagonistNameRequiredError(error: unknown): boolean {
  return isApiError(error) && error.status === 422 && detailCode(error.detail) === "NOVEL_PROTAGONIST_NAME_REQUIRED";
}

const FAILURE_SUBJECT: Record<NovelJobResponse["kind"], string> = {
  chapter_generate: "새 화를 만들지 못했어요.",
  chapter_regenerate: "화를 다시 만들지 못했어요.",
  ai_edit: "AI로 고치지 못했어요.",
  chain_generate: "남은 대화를 소설로 만들지 못했어요.",
};

/** 실패로 끝난 작업의 안내. 돌려준 클로버는 서버가 적은 환불액(`refundedAmount`)을 그대로 말한다 — 묶음·연쇄는 일부만
 * 돌려줄 수 있어 낸 금액(`chargedAmount`)과 다를 수 있다. 돌려준 것이 없으면 환불을 말하지 않는다. */
export function toNovelJobFailureMessage(job: Pick<NovelJobResponse, "kind" | "failureReason" | "refundedAmount">): string {
  return `${failureReasonSentence(job)}${toRefundSentence(job.refundedAmount)}`;
}

/** 돌려준 클로버 한 문장(앞에 띄어쓰기 포함). 없으면 빈 문자열이다. */
export function toRefundSentence(refundedAmount: number): string {
  return refundedAmount > 0 ? ` 쓴 클로버 ${refundedAmount.toLocaleString()}개는 돌려드렸어요.` : "";
}

function failureReasonSentence(job: Pick<NovelJobResponse, "kind" | "failureReason">): string {
  switch (job.failureReason) {
    case "refused":
    case "blocked":
      return `${FAILURE_SUBJECT[job.kind]} 안전 기준에 걸리는 내용이 있었어요.`;
    case "source_changed":
      if (job.kind === "ai_edit") return "고치는 동안 화가 바뀌어 수정안을 쓸 수 없게 됐어요.";
      if (job.kind === "chain_generate") return "원래 대화가 바뀌어 남은 대화를 이어 만들 수 없어요.";
      return "원래 대화가 바뀌어 이 화는 다시 만들 수 없어요.";
    // 모델이 약속한 글 형식이나 화 수를 지키지 않았다 — 같은 요청으로 다시 하면 대개 맞게 나온다.
    case "malformed":
      return `${FAILURE_SUBJECT[job.kind]} AI가 쓴 글의 형식이 맞지 않았어요.`;
    case "episode_count_mismatch":
      return `${FAILURE_SUBJECT[job.kind]} AI가 지금과 다른 화 수로 썼어요.`;
    default:
      return FAILURE_SUBJECT[job.kind];
  }
}
