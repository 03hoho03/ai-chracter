import type { CloverProductItem } from "@/entities/clover";

import type { PurchaseSection } from "./purchaseSection";

/** 상품 안내 화면에서 고르고 온 상품(`?product=`) 중 지금 구매 확인을 열어도 되는 것.
 *
 * 구매 섹션이 상품 목록을 보여 주는 상태일 때만 연다 — 결제가 닫혔거나 본인인증·나이 때문에 살 수 없는 회원에게
 * 결제 폼을 열면 다 채운 뒤에야 거절된다. 그때 화면은 구매 섹션의 안내 문장이 대신 말한다. 가격 응답에 없는 키(옛 링크,
 * 손으로 고친 주소)는 아무것도 열지 않는다. */
export function findRequestedProduct(
  products: readonly CloverProductItem[],
  productKey: string | undefined,
  section: PurchaseSection,
): CloverProductItem | undefined {
  if (productKey === undefined || section !== "products") return undefined;
  return products.find((product) => product.key === productKey);
}
