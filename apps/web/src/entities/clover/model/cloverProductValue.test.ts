import { describe, expect, it } from "vitest";

import type { CloverProductItem } from "../api/useCloverPricingQuery";
import { getCloverBonusRate } from "./cloverProductValue";

function product(priceKrw: number, paidAmount: number, bonusAmount: number): CloverProductItem {
  return { key: "lite", name: "라이트", priceKrw, paidAmount, bonusAmount };
}

describe("getCloverBonusRate", () => {
  it("유료 클로버 대비 보너스 비율을 정수 퍼센트로 준다", () => {
    expect(getCloverBonusRate(product(4500, 1500, 75))).toBe(5);
    expect(getCloverBonusRate(product(49500, 16500, 3300))).toBe(20);
  });

  it("보너스가 없으면 비율을 말하지 않는다", () => {
    expect(getCloverBonusRate(product(900, 300, 0))).toBeNull();
  });

  it("유료 수량이 0이면 나누지 않는다", () => {
    expect(getCloverBonusRate(product(0, 0, 10))).toBeNull();
  });
});
