import { isApiError } from "@/shared/api/client";

import type { CompletePaymentStatus } from "../api/useCompletePaymentMutation";

/** 구매 시도 하나가 어떻게 끝났는지. 다이얼로그(PC)와 리다이렉트 복귀(모바일)가 같은 어휘로 안내한다.
 *
 * - `paid` — 지급까지 끝났다.
 * - `checking` — 결제사가 아직 확정하지 않았거나 확인 요청이 실패했다. 돈이 나갔을 수 있으므로 실패라고 말하지 않는다 —
 *   웹훅이 같은 결제를 맞춰 지급하면 잔액에 보인다.
 * - `problem` — 서버가 지급하지 않기로 했다(금액 불일치 등). 이용자가 할 수 있는 일은 문의뿐이다.
 * - `notCompleted` — 결제창이 실패 코드로 닫혔다(취소 포함). 오류가 아니다.
 * - `redirecting` — 결제창이 페이지를 떠난다. 돌아오면 리다이렉트 처리가 이어받는다.
 * - `ageRestricted`·`identityRequired`·`reconsentRequired`·`unavailable` — 주문을 만들기 전에 서버가 막았다.
 * - `failed` — 주문이나 결제창 요청이 실패했다.
 * - `sdkUnavailable` — 결제창 SDK 를 못 불러왔다. 새로고침해야 풀린다. */
export type PurchaseResult =
  | "paid"
  | "checking"
  | "problem"
  | "notCompleted"
  | "redirecting"
  | "ageRestricted"
  | "identityRequired"
  | "reconsentRequired"
  | "unavailable"
  | "failed"
  | "sdkUnavailable";

export function toPurchaseResult(status: CompletePaymentStatus): PurchaseResult {
  switch (status) {
    case "paid":
      return "paid";
    case "pending":
      return "checking";
    case "failed":
    case "mismatch":
    case "owner_withdrawn":
    case "cancelled":
    case "partially_cancelled":
      return "problem";
  }
}

/** 주문 생성 실패를 화면 갈래로.
 *
 * 본인인증·재동의 403 은 다이얼로그를 닫는 갈래다 — 둘 다 전역 뮤테이션 처리가 세션을 다시 읽어 화면이 바뀐다(허브는
 * 본인인증 안내, 앱은 재동의 모달). 일반 오류로 접으면 다이얼로그 안 "결제를 시작하지 못했어요 · 문의"가 그 모달과
 * 겹친다. */
export function toCreatePaymentFailure(error: unknown): PurchaseResult {
  const code = isApiError(error) && error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
  switch (code) {
    case "PAYMENT_AGE_RESTRICTED":
      return "ageRestricted";
    case "IDENTITY_VERIFICATION_REQUIRED":
      return "identityRequired";
    case "LEGAL_RECONSENT_REQUIRED":
      return "reconsentRequired";
    case "PAYMENTS_UNAVAILABLE":
      return "unavailable";
    default:
      return "failed";
  }
}

export const PURCHASE_MESSAGES = {
  paid: "클로버를 충전했어요.",
  checking: "결제를 확인하고 있어요. 확인되면 잔액에 반영돼요.",
  problem: "결제를 확인하지 못했어요. 문의해 주시면 확인해 드릴게요.",
  notCompleted: "결제가 완료되지 않았어요.",
  ageRestricted: "만 19세 이상만 클로버를 구매할 수 있어요.",
  unavailable: "지금은 결제할 수 없어요. 잠시 후 다시 시도해 주세요.",
  failed: "결제를 시작하지 못했어요. 문제가 계속되면 문의해 주세요.",
  sdkUnavailable: "결제창을 불러오지 못했어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
} as const satisfies Partial<Record<PurchaseResult, string>>;
