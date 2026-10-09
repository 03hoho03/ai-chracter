import type { CloverProductItem } from "../api/useCloverPricingQuery";

/** 상품끼리 견줄 단서 둘 — 보너스율과 클로버 한 개 값. 둘 다 응답의 가격·수량에서 계산할 뿐 숫자 사본을 두지 않는다.
 *
 * 보너스율은 유료 클로버 대비 보너스 비율이다(1,500개에 75개면 5%). 보너스가 없으면 `null` 이라 "보너스 0%"를 쓰지
 * 않는다. 클로버 한 개 값은 판매가를 받는 클로버 전체(유료 + 보너스)로 나눈 값이고, 상품 사이 차이가 1원 안이라
 * 소수 둘째 자리까지 보인다. 나눌 수량이 0이면 계산하지 않는다. */
export function getCloverBonusRate(product: CloverProductItem): number | null {
  if (product.bonusAmount <= 0 || product.paidAmount <= 0) return null;
  return Math.round((product.bonusAmount / product.paidAmount) * 100);
}

export function formatCloverUnitPrice(product: CloverProductItem): string | null {
  const total = product.paidAmount + product.bonusAmount;
  if (total <= 0) return null;
  return (product.priceKrw / total).toLocaleString("ko-KR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
