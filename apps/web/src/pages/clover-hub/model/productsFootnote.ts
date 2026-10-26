import { PURCHASE_CONDITION_SENTENCES } from "./cloverPolicy";
import type { PurchaseSection } from "./purchaseSection";

/** 상품 목록 아래 한 줄 — 행을 누르면 무슨 일이 일어나는지, 또는 왜 누를 수 없는지.
 *
 * 본인인증 전·만 19세 미만의 이유는 구매 조건이 이미 말한다. 좁은 화면에서는 구매 조건이 상품 바로 위라 되풀이하지 않고,
 * 넓은 화면에서는 구매 조건이 옆 열에 있어 누를 수 없는 행 아래에서 이유가 바로 읽히지 않으므로 그때만 덧붙인다
 * (`isWideOnly`). */
export type ProductsFootnote = { text: string; isWideOnly: boolean };

export function getProductsFootnote(section: PurchaseSection): ProductsFootnote | null {
  switch (section) {
    case "guest":
      return { text: "상품을 고르면 로그인한 뒤 그 상품의 결제로 이어져요.", isWideOnly: false };
    case "disabled":
      return { text: "클로버 결제는 아직 준비 중이에요.", isWideOnly: false };
    case "identityRequired":
      return { text: "본인인증을 마치면 살 수 있어요.", isWideOnly: true };
    case "ageRestricted":
      return { text: PURCHASE_CONDITION_SENTENCES.ageRestricted, isWideOnly: true };
    case "products":
    case "pending":
      return null;
  }
}
