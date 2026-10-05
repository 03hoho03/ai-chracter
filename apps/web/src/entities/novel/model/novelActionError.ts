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
  | "deleteNovel";

export type NovelActionErrorNotice = {
  message: string;
  /** 상세를 다시 받아야 화면이 맞아지는 실패인가 — 단가·진행 중 작업·장 목록·대화방 유무가 서버에서 바뀌었다는
   * 뜻이다. 진행 중 작업 409 는 다시 받은 상세의 `activeJob` 으로 폴링을 이어 간다. */
  shouldRefetchNovel: boolean;
};

const ACTION_OBJECT: Record<NovelAction, string> = {
  proposal: "다음 장을 준비하지",
  generate: "장을 만들지",
  regenerate: "장을 다시 만들지",
  aiEdit: "AI로 고치지",
  applyAiEdit: "수정안을 적용하지",
  dismissAiEdit: "수정안을 버리지",
  edit: "고친 내용을 저장하지",
  restore: "이 판으로 되돌리지",
  notes: "설정 노트를 저장하지",
  deleteChapter: "장을 지우지",
  deleteNovel: "소설을 지우지",
};

/** 원래 대화방이 지워져 장을 만들 수도 다시 만들 수도 없을 때의 문장. 만들기 버튼 아래 사유 문장과 두 요청의 409 가
 * 같은 문장을 쓴다 — 409 문구는 요청 종류를 보지 않아서, 만들기만 말하면 다시 만들기에서 받았을 때 틀린 말이 된다. */
export const NOVEL_ROOM_GONE_MESSAGE = "원래 대화방이 지워져 새 장을 만들거나 다시 만들 수 없어요.";

/** 코드 → 문구. 기다려도 풀리지 않는 거부는 "다시 시도"를 말하지 않고, 이용자가 할 수 있는 다음 일을 말한다. */
const MESSAGE_BY_CODE: Record<string, NovelActionErrorNotice> = {
  NOVELIZE_NOT_ALLOWED: { message: "소설로 보기를 지금 이 계정에서 쓸 수 없어요.", shouldRefetchNovel: false },
  NOVEL_NOT_FOUND: { message: "소설이 지워졌어요. 내 소설에서 다시 확인해주세요.", shouldRefetchNovel: true },
  NOVEL_FORBIDDEN: { message: "이 계정의 소설이 아니에요.", shouldRefetchNovel: true },
  NOVEL_CURSOR_INVALID: { message: "목록을 처음부터 다시 불러와주세요.", shouldRefetchNovel: false },
  NOVEL_JOB_NOT_FOUND: { message: "작업을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_CHAPTER_NOT_FOUND: { message: "이 장이 지워졌어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_NOT_FOUND: { message: "이 판을 찾을 수 없어요. 소설을 다시 불러왔어요.", shouldRefetchNovel: true },
  NOVEL_ROOM_GONE: { message: NOVEL_ROOM_GONE_MESSAGE, shouldRefetchNovel: true },
  NOVEL_PROTAGONIST_NAME_REQUIRED: { message: "주인공 이름을 먼저 정해주세요.", shouldRefetchNovel: true },
  NOVEL_NOTHING_NEW: {
    message: "장으로 묶을 새 대화가 없어요. 대화를 더 이어 간 뒤 만들어주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_END_INVALID: {
    message: "고른 턴으로는 장을 끝낼 수 없어요. 다음 장 만들기를 다시 눌러 골라주세요.",
    shouldRefetchNovel: true,
  },
  NOVEL_CHAPTER_NOT_LAST: { message: "마지막 장만 지울 수 있어요.", shouldRefetchNovel: true },
  NOVEL_PARAGRAPH_RANGE_INVALID: { message: "고른 문단이 바뀌었어요. 다시 골라주세요.", shouldRefetchNovel: true },
  NOVEL_JOB_NOT_APPLICABLE: { message: "이 수정안은 더 이상 적용할 수 없어요.", shouldRefetchNovel: true },
  NOVEL_REVISION_CONFLICT: {
    message: "다른 곳에서 먼저 고쳤어요. 최신 내용을 불러왔어요.",
    shouldRefetchNovel: true,
  },
  NOVEL_SOURCE_CHANGED: {
    message: "원래 대화가 바뀌어 이 장은 다시 만들 수 없어요.",
    shouldRefetchNovel: false,
  },
  NOVEL_JOB_IN_PROGRESS: {
    message: "이미 진행 중인 작업이 있어요. 끝나면 다시 해주세요.",
    shouldRefetchNovel: true,
  },
  CONTENT_RESTRICTED: {
    message: "이용이 제한된 작품이라 새로 쓰는 작업을 할 수 없어요. 지금까지 만든 장은 그대로 볼 수 있어요.",
    shouldRefetchNovel: false,
  },
};

function detailCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  const { code } = detail;
  return typeof code === "string" ? code : undefined;
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
        ? { message: "다음 장 준비를 너무 자주 요청했어요. 잠시 후 다시 시도해주세요.", shouldRefetchNovel: false }
        : {
            message: "같은 장을 오늘 만들 수 있는 횟수를 다 썼어요. 자정이 지나면 다시 만들 수 있어요.",
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
  return MESSAGE_BY_CODE[code] ?? fallback(action);
}

/** 서버가 재시도 전에 주인공 이름을 먼저 받으라고 한 422 인가. 상세의 이름이 낡았을 때(다른 탭이 비웠거나 첫
 * 조회 뒤 바뀌었을 때) 장 만들기 흐름이 이름 입력으로 돌아가는 신호다. */
export function isProtagonistNameRequiredError(error: unknown): boolean {
  return isApiError(error) && error.status === 422 && detailCode(error.detail) === "NOVEL_PROTAGONIST_NAME_REQUIRED";
}

const FAILURE_SUBJECT: Record<NovelJobResponse["kind"], string> = {
  chapter_generate: "새 장을 만들지 못했어요.",
  chapter_regenerate: "장을 다시 만들지 못했어요.",
  ai_edit: "AI로 고치지 못했어요.",
};

/** 실패로 끝난 작업의 안내. 실패한 작업은 서버가 언제나 환불하므로 환불을 함께 말한다(`refunded` 가 거짓인 실패는
 * 계약에 없지만, 있다면 거짓말하지 않도록 그때는 환불을 말하지 않는다). */
export function toNovelJobFailureMessage(job: Pick<NovelJobResponse, "kind" | "failureReason" | "refunded" | "chargedAmount">): string {
  const reason = failureReasonSentence(job);
  const refund = job.refunded && job.chargedAmount > 0 ? ` 쓴 클로버 ${job.chargedAmount.toLocaleString()}개는 돌려드렸어요.` : "";
  return `${reason}${refund}`;
}

function failureReasonSentence(job: Pick<NovelJobResponse, "kind" | "failureReason">): string {
  switch (job.failureReason) {
    case "refused":
    case "blocked":
      return `${FAILURE_SUBJECT[job.kind]} 안전 기준에 걸리는 내용이 있었어요.`;
    case "source_changed":
      return job.kind === "ai_edit"
        ? "고치는 동안 장이 바뀌어 수정안을 쓸 수 없게 됐어요."
        : "원래 대화가 바뀌어 이 장은 다시 만들 수 없어요.";
    default:
      return FAILURE_SUBJECT[job.kind];
  }
}
