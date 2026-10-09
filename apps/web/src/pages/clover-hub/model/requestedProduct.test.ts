import { describe, expect, it } from "vitest";

import type { CloverProductItem } from "@/entities/clover";

import { findRequestedProduct } from "./requestedProduct";

const LITE: CloverProductItem = { key: "lite", name: "라이트", priceKrw: 4500, paidAmount: 1500, bonusAmount: 75 };
const MAX: CloverProductItem = { key: "max", name: "맥스", priceKrw: 49500, paidAmount: 16500, bonusAmount: 3300 };
const PRODUCTS = [LITE, MAX];

describe("findRequestedProduct", () => {
  it("살 수 있는 상태면 고른 상품을 찾는다", () => {
    expect(findRequestedProduct(PRODUCTS, "max", "products")).toBe(MAX);
  });

  it("고른 상품이 없으면 아무것도 열지 않는다", () => {
    expect(findRequestedProduct(PRODUCTS, undefined, "products")).toBeUndefined();
  });

  it("가격 응답에 없는 키는 아무것도 열지 않는다", () => {
    expect(findRequestedProduct(PRODUCTS, "pro", "products")).toBeUndefined();
  });

  // 결제가 닫혔거나 살 수 없는 회원에게 결제 폼을 열면 다 채운 뒤에야 거절된다.
  it.each(["disabled", "identityRequired", "ageRestricted"] as const)("구매 섹션이 %s 면 열지 않는다", (section) => {
    expect(findRequestedProduct(PRODUCTS, "lite", section)).toBeUndefined();
  });
});
