import type { CloverProductItem } from "../api/useCloverPricingQuery";

/** 상품끼리 견줄 단서인 보너스율. 응답의 수량에서 계산할 뿐 숫자 사본을 두지 않는다.
 *
 * 보너스율은 유료 클로버 대비 보너스 비율이다(1,500개에 75개면 5%). 보너스가 없으면 `null` 이라 "보너스 0%"를 쓰지
 * 않는다. 나눌 유료 수량이 0이면 계산하지 않는다. */
export function getCloverBonusRate(product: CloverProductItem): number | null {
  if (product.bonusAmount <= 0 || product.paidAmount <= 0) return null;
  return Math.round((product.bonusAmount / product.paidAmount) * 100);
}
