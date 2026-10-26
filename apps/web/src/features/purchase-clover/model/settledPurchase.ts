import { isApiError } from "@/shared/api/client";

import type { CompletePaymentResponse } from "../api/useCompletePaymentMutation";
import { toPurchaseResult, type CompletedPurchaseResult } from "./purchaseResult";

/** 이 결제로 받은 유료·보너스 클로버 수. 서버가 지급한 로트에서 읽어 결제 완료 응답에 싣는다 — 화면이 상품표로 계산하면
 * 가격이 바뀌거나 단위가 바뀐 경계에서 틀린 숫자를 성공처럼 보인다. */
export type PurchaseGrant = { paid: number; bonus: number };

/** 구매 확인 창 밖(충전 화면)에서 알려야 하는 끝난 결과. 창 안에 남는 결과(고쳐서 다시 누를 수 있는 것)는 여기 없다.
 * `grant` 는 지급까지 끝났고 서버가 받은 수량을 실었을 때만 있다. */
export type SettledPurchase = {
  result: CompletedPurchaseResult;
  grant: PurchaseGrant | null;
};

/** 화면이 읽는 완료 응답. web 과 API 는 따로 배포돼 받은 수량 칸이 아예 없는 옛 응답을 받는 구간이 있다 — 타입은 그
 * 칸을 필수로 적지만 그 구간에는 런타임에 비어 있으므로 비어 있을 수 있는 모양으로 읽는다. */
type DeployedCompletePaymentResponse = Pick<CompletePaymentResponse, "status"> &
  Partial<Pick<CompletePaymentResponse, "grantedPaid" | "grantedBonus">>;

export function toSettledPurchase(response: DeployedCompletePaymentResponse): SettledPurchase {
  const result = toPurchaseResult(response.status);
  const { grantedPaid, grantedBonus } = response;
  const grant =
    result === "paid" && typeof grantedPaid === "number" && typeof grantedBonus === "number"
      ? { paid: grantedPaid, bonus: grantedBonus }
      : null;
  return { result, grant };
}

/** 결제 완료 확인 요청이 실패했을 때 화면에 그릴 결과. 대개 확인 요청만 실패한 것이라(포트원 조회 실패 등) 결제는 됐을
 * 수 있고 웹훅이 같은 결제를 맞춘다 — 그래서 "확인 중"이다. 예외는 서버가 이 계정의 결제가 아니라고 답한 404 다(결제창에서
 * 돌아오는 사이 다른 계정으로 로그인한 경우). 그 결제는 이 계정에 지급되지 않으므로 "확인 중"이라고 하면 오지 않을 지급을
 * 기다리게 한다 — 결과를 그리지 않는다(`null`). */
export function settleFailedCompletion(error: unknown): SettledPurchase | null {
  const code = isApiError(error) && error.detail && typeof error.detail === "object" ? error.detail.code : undefined;
  if (code === "PAYMENT_NOT_FOUND") return null;
  return { result: "checking", grant: null };
}

/** 받은 수량 문장. 보너스가 없는 상품이면 보너스를 말하지 않는다. */
export function formatPurchaseGrant(grant: PurchaseGrant): string {
  return grant.bonus > 0
    ? `유료 ${grant.paid.toLocaleString()}개와 보너스 ${grant.bonus.toLocaleString()}개를 받았어요.`
    : `유료 ${grant.paid.toLocaleString()}개를 받았어요.`;
}
