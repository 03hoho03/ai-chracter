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

/** 받은 수량 문장. 보너스가 없는 상품이면 보너스를 말하지 않는다. */
export function formatPurchaseGrant(grant: PurchaseGrant): string {
  return grant.bonus > 0
    ? `유료 ${grant.paid.toLocaleString()}개와 보너스 ${grant.bonus.toLocaleString()}개를 받았어요.`
    : `유료 ${grant.paid.toLocaleString()}개를 받았어요.`;
}
