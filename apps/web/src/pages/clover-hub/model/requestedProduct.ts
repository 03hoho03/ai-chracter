import type { PurchaseSection } from "./purchaseSection";

/** 주소에 담겨 온 상품(`?product=`)을 어떻게 다룰지.
 *
 * - `none` — 담긴 상품이 없거나, 지금은 말할 것이 없다(세션 대기, 결제 꺼짐·나이 제한 — 그 이유는 구매 조건이 이미 말한다).
 * - `open` — 살 수 있다. 그 상품의 구매 확인을 바로 연다.
 * - `chosen` — 로그인하지 않았다. 고른 맥락을 잃지 않게 상품 이름·가격을 알리고, 로그인하면 결제로 이어진다고 말한다.
 * - `afterIdentity` — 본인인증 전이다. 인증을 마치면 그 상품을 여기서 살 수 있다고 말한다.
 * - `unavailable` — 응답에 없는 키다(판매 종료·옛 링크·손으로 고친 주소). 다른 상품으로 바꿔 열지 않고 그렇다고만 말한다
 *   — 비슷한 상품을 대신 열면 고르지 않은 금액으로 결제가 이어진다. */
export type RequestedProduct<Product> =
  | { kind: "none" }
  | { kind: "open"; product: Product }
  | { kind: "chosen"; product: Product }
  | { kind: "afterIdentity"; product: Product }
  | { kind: "unavailable" };

export function resolveRequestedProduct<Product extends { key: string }>(
  products: readonly Product[],
  productKey: string | undefined,
  section: PurchaseSection,
): RequestedProduct<Product> {
  if (productKey === undefined) return { kind: "none" };
  if (section === "pending" || section === "disabled" || section === "ageRestricted") return { kind: "none" };

  const product = products.find((candidate) => candidate.key === productKey);
  if (!product) return { kind: "unavailable" };
  switch (section) {
    case "products":
      return { kind: "open", product };
    case "guest":
      return { kind: "chosen", product };
    case "identityRequired":
      return { kind: "afterIdentity", product };
  }
}
