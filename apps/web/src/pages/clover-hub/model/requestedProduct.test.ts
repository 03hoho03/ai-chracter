import { describe, expect, it } from "vitest";

import { resolveRequestedProduct } from "./requestedProduct";

const LITE = { key: "lite", name: "라이트" };
const MAX = { key: "max", name: "맥스" };
const PRODUCTS = [LITE, MAX];

describe("resolveRequestedProduct", () => {
  it("담긴 상품이 없으면 아무것도 하지 않는다", () => {
    expect(resolveRequestedProduct(PRODUCTS, undefined, "products")).toEqual({ kind: "none" });
  });

  it("살 수 있으면 고른 상품의 구매 확인을 연다", () => {
    expect(resolveRequestedProduct(PRODUCTS, "max", "products")).toEqual({ kind: "open", product: MAX });
  });

  // 로그인하러 가기 전에 무엇을 골랐는지 잃지 않게 한다.
  it("로그인하지 않았으면 고른 상품을 알린다", () => {
    expect(resolveRequestedProduct(PRODUCTS, "lite", "guest")).toEqual({ kind: "chosen", product: LITE });
  });

  it("본인인증 전이면 인증 뒤에 살 수 있다고 알린다", () => {
    expect(resolveRequestedProduct(PRODUCTS, "lite", "identityRequired")).toEqual({
      kind: "afterIdentity",
      product: LITE,
    });
  });

  // 비슷한 상품을 대신 열면 고르지 않은 금액으로 결제가 이어진다.
  it.each(["products", "guest", "identityRequired"] as const)(
    "응답에 없는 키는 다른 상품으로 바꾸지 않고 판매하지 않는다고 알린다 (%s)",
    (section) => {
      expect(resolveRequestedProduct(PRODUCTS, "basic", section)).toEqual({ kind: "unavailable" });
    },
  );

  // 결제가 닫혔거나 나이 때문에 살 수 없으면 구매 조건이 이유를 이미 말한다. 세션 대기 중에는 갈래를 아직 모른다.
  it.each(["pending", "disabled", "ageRestricted"] as const)("%s 이면 말하지 않는다", (section) => {
    expect(resolveRequestedProduct(PRODUCTS, "lite", section)).toEqual({ kind: "none" });
    expect(resolveRequestedProduct(PRODUCTS, "basic", section)).toEqual({ kind: "none" });
  });
});
