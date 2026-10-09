import type { ApiError } from "@ai-character-chat/api-types";

import { CREATOR_PAYOUT_BLOCK_REASON_LABELS, toCreatorPayoutBlockReason } from "@/entities/creator-payout-application";
import { isApiError } from "@/shared/lib/api/client";

/**
 * 처리 실패를 둘로 가른다.
 * - `stale`: 화면의 행이 낡아 이 처리를 다시 해도 같은 거부가 온다(이미 처리됨·자격 바뀜·없는 신청). 모달을 닫고
 *   알린다 — 목록은 뮤테이션이 이미 다시 읽었다.
 * - `retry`: 서버·네트워크 실패. 입력을 살려 둔 채 모달 안에 알린다.
 */
export type DecisionFailure = { kind: "stale"; message: string } | { kind: "retry"; message: string };

const RETRY_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

export function toDecisionFailure(error: unknown): DecisionFailure {
  if (!isApiError(error)) return { kind: "retry", message: RETRY_MESSAGE };
  switch (detailCode(error)) {
    case "CREATOR_PAYOUT_APPLICATION_NOT_FOUND":
      return { kind: "stale", message: "신청을 찾지 못했어요. 목록을 다시 불러왔어요." };
    case "CREATOR_PAYOUT_APPLICATION_NOT_PENDING":
      return { kind: "stale", message: "이미 처리된 신청이에요. 목록을 다시 불러왔어요." };
    case "CREATOR_PAYOUT_APPLICATION_NOT_APPROVED":
      return { kind: "stale", message: "승인 상태가 아닌 신청이에요. 이미 취소됐을 수 있어요." };
    case "CREATOR_PAYOUT_NOT_ELIGIBLE": {
      const reason = toCreatorPayoutBlockReason(detailField(error, "reason"));
      return {
        kind: "stale",
        message: reason
          ? `신청자가 지금 자격이 없어 승인하지 못했어요(${CREATOR_PAYOUT_BLOCK_REASON_LABELS[reason]}).`
          : "신청자가 지금 자격이 없어 승인하지 못했어요.",
      };
    }
    default:
      return { kind: "retry", message: RETRY_MESSAGE };
  }
}

/** 거부 code 는 OpenAPI 에 실리지 않아 생성 타입이 없다 — 구조화된 `detail` 을 직접 읽는다. */
function detailCode(error: ApiError) {
  const code = detailField(error, "code");
  return typeof code === "string" ? code : null;
}

function detailField(error: ApiError, key: string): unknown {
  return typeof error.detail === "object" ? error.detail[key] : undefined;
}
