import { isApiError } from "@/shared/api/client";
import { getRateLimitDetail } from "@/shared/api/rateLimit";

/** 요약 다시 만들기가 실패했을 때 확인 대화가 할 일.
 * - `priceChanged`: 확인한 가격이 지금 가격과 달라 깎기 전에 거절됐다. 새 가격으로 다시 묻는다(서버가 숫자를 주지 않으면
 *   가격표를 다시 받아 쓴다).
 * - `inProgress`: 같은 방에서 다시 만들기가 이미 돌고 있다. 깎지 않았다.
 * - `stale`: 확인 대화를 연 뒤 요약이 바뀌었거나 사라졌다. 기억을 다시 받아 바뀐 요약으로 다시 묻는다.
 * - `cloverRequired`: 잔액이 모자라 깎지 않았다. 실행 버튼이 "클로버 채우기"로 바뀐다(문장은 금액 줄이 말한다).
 * - `unavailable`: 깎은 뒤 요약을 만들지 못해 돌려줬다.
 * - `disabled`: 서버 스위치가 꺼졌다. 기억을 다시 받으면 버튼이 사라진다.
 * - `message`: 그 밖. 환불을 약속하지 않는다 — 깎기 전에 실패했는지 알 수 없다. 재동의 403 은 앱 전역 오류 처리가 맡는다. */
export type RegenerateSummaryFailure =
  | { kind: "priceChanged"; currentCost: number | undefined; message: string }
  | { kind: "inProgress"; message: string }
  | { kind: "stale"; message: string }
  | { kind: "cloverRequired" }
  | { kind: "unavailable"; message: string }
  | { kind: "disabled"; message: string }
  | { kind: "message"; message: string };

const GENERIC_MESSAGE = "요약을 다시 만들지 못했어요. 잠시 후 다시 시도해 주세요.";

export function toRegenerateSummaryFailure(error: unknown): RegenerateSummaryFailure {
  const rateLimit = getRateLimitDetail(error);
  if (rateLimit?.window === "memory_summary" && rateLimit.code === "CLOVER_REQUIRED") return { kind: "cloverRequired" };
  if (!isApiError(error)) return { kind: "message", message: GENERIC_MESSAGE };

  const code = detailCode(error.detail);
  if (error.status === 409) {
    if (code === "MEMORY_SUMMARY_REGENERATE_PRICE_CHANGED") {
      return {
        kind: "priceChanged",
        currentCost: currentCostOf(error.detail),
        message: "그사이 가격이 바뀌었어요. 바뀐 금액을 확인하고 다시 눌러 주세요.",
      };
    }
    if (code === "MEMORY_SUMMARY_REGENERATE_IN_PROGRESS") {
      return { kind: "inProgress", message: "이 대화방의 요약을 이미 다시 만들고 있어요. 끝나면 요약이 바뀌어요." };
    }
    if (code === "MEMORY_VERSION_CONFLICT" || code === "MEMORY_SUMMARY_NOT_READY") {
      return { kind: "stale", message: "그사이 요약이 바뀌었어요. 바뀐 요약을 확인하고 다시 눌러 주세요." };
    }
  }
  if (error.status === 503 && code === "MEMORY_SUMMARY_REGENERATE_UNAVAILABLE") {
    return {
      kind: "unavailable",
      message: "요약을 다시 만들지 못했어요. 쓴 클로버는 돌려드렸어요. 잠시 후 다시 시도해 주세요.",
    };
  }
  if (error.status === 404 && code === "MEMORY_ITEMS_DISABLED") {
    return { kind: "disabled", message: "지금은 요약을 다시 만들 수 없어요." };
  }
  if (error.status === 403 && code === "CONTENT_RESTRICTED") {
    return { kind: "message", message: "이용이 제한된 작품이라 요약을 다시 만들 수 없어요." };
  }
  return { kind: "message", message: GENERIC_MESSAGE };
}

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
