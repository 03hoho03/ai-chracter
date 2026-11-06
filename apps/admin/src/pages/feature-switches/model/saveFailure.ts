import type { ApiError } from "@ai-character-chat/api-types";

import { apiErrorCode, isApiError } from "@/shared/lib/api/client";

/**
 * 저장(바꾸기·덮어쓰기 지우기) 실패를 모달이 할 일로 가른다. 목록·이력은 뮤테이션이 실패마다 이미 다시 읽었다.
 * - `field`: 사유 칸 오류로 보인다.
 * - `inline`: 모달을 열어 둔 채 사유를 살리고 확정 버튼 위에 알린다(선행 조건 거절, 결과를 모르는 실패).
 * - `close`: 화면이 본 값이 낡아 다시 눌러도 같은 거절이 온다 — 모달을 닫고 토스트로 알린다.
 */
export type SaveFailure =
  | { kind: "field"; message: string }
  | { kind: "inline"; message: string }
  | { kind: "close"; message: string };

/** 기능 스위치 저장의 거절 code. 거절 code 는 OpenAPI 에 실리지 않아 생성 타입이 없어 서버 라우터의 거절을 여기 옮겨 적는다. */
type FeatureSwitchRefusalCode =
  | "FEATURE_SWITCH_READ_ONLY"
  | "FEATURE_SWITCH_REASON_REQUIRED"
  | "FEATURE_SWITCH_REASON_TOO_LONG"
  | "FEATURE_SWITCH_STALE"
  | "FEATURE_SWITCH_UNCHANGED"
  | "CLOVER_PAUSE_REFUNDS_IN_PROGRESS"
  | "NOVEL_ILLUSTRATIONS_REVIEW_LANE_MISSING";

const REFUSALS = {
  FEATURE_SWITCH_READ_ONLY: () => ({
    kind: "close",
    message: "이 스위치는 이제 어드민에서 바꿀 수 없어요(서버 판이 바뀌었을 수 있어요). 목록을 다시 불러올게요.",
  }),
  FEATURE_SWITCH_REASON_REQUIRED: () => ({ kind: "field", message: "사유를 입력해주세요." }),
  FEATURE_SWITCH_REASON_TOO_LONG: () => ({ kind: "field", message: "사유는 1,000자까지 쓸 수 있어요." }),
  FEATURE_SWITCH_STALE: () => ({
    kind: "close",
    message: "다른 운영자가 방금 이 스위치를 바꿨어요. 최신 값을 불러올게요 — 확인하고 다시 시도하세요.",
  }),
  FEATURE_SWITCH_UNCHANGED: () => ({ kind: "close", message: "이미 그 값이에요. 목록을 다시 불러올게요." }),
  CLOVER_PAUSE_REFUNDS_IN_PROGRESS: (error) => {
    const count = detailField(error, "requestedCount");
    const counted = typeof count === "number" ? `진행 중인 환불이 ${count}건 있어` : "진행 중인 환불이 있어";
    return {
      kind: "inline",
      message: `${counted} 정지를 켤 수 없어요. 정지 중에는 그 환불을 마무리하는 라우트도 막혀요 — 회원 상세의 결제 환불에서 먼저 끝내 주세요.`,
    };
  },
  NOVEL_ILLUSTRATIONS_REVIEW_LANE_MISSING: () => ({
    kind: "inline",
    message:
      "삽화를 심사할 프롬프트 세트가 없어 켤 수 없어요. 켜면 그림이 있는 공개가 503 이 돼요 — 프롬프트 관리의 「발행 검열」 레인에 세트를 먼저 게시하세요.",
  }),
} satisfies Record<FeatureSwitchRefusalCode, (error: ApiError) => SaveFailure>;

function isRefusalCode(code: string): code is FeatureSwitchRefusalCode {
  return code in REFUSALS;
}

export function toSaveFailure(error: unknown): SaveFailure {
  const code = apiErrorCode(error);
  if (isApiError(error) && code !== null && isRefusalCode(code)) return REFUSALS[code](error);
  // 응답이 없거나 서버 오류면 커밋 뒤에 끊겼을 수 있다 — 실패했다고 단정하지 않는다.
  if (!isApiError(error) || error.status === 0 || error.status >= 500) {
    return {
      kind: "inline",
      message: "저장 결과를 받지 못했어요. 저장됐을 수도 있으니 목록에서 지금 값을 확인한 뒤 다시 시도하세요.",
    };
  }
  return { kind: "inline", message: "저장하지 못했어요. 새로고침한 뒤 다시 시도해주세요." };
}

function detailField(error: ApiError, key: string): unknown {
  return typeof error.detail === "object" ? error.detail[key] : undefined;
}
