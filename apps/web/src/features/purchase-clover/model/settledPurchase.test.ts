import { describe, expect, it } from "vitest";

import { formatPurchaseGrant, toSettledPurchase } from "./settledPurchase";

describe("toSettledPurchase", () => {
  it("지급까지 끝났으면 서버가 실은 받은 수량을 함께 낸다", () => {
    expect(toSettledPurchase({ status: "paid", grantedPaid: 9900, grantedBonus: 990 })).toEqual({
      result: "paid",
      grant: { paid: 9900, bonus: 990 },
    });
  });

  // 받은 수량을 상품표로 추정하면 가격·단위가 바뀐 경계에서 틀린 숫자를 성공처럼 보인다.
  it("서버가 받은 수량을 싣지 않았으면 수량 없이 성공만 낸다", () => {
    expect(toSettledPurchase({ status: "paid", grantedPaid: null, grantedBonus: null })).toEqual({
      result: "paid",
      grant: null,
    });
  });

  // 확인 중에는 아직 지급하지 않았을 수 있다 — 받았다고 말하면 거짓일 수 있다.
  it("확인 중이면 수량이 와도 싣지 않는다", () => {
    expect(toSettledPurchase({ status: "pending", grantedPaid: 9900, grantedBonus: 990 })).toEqual({
      result: "checking",
      grant: null,
    });
  });

  it.each([
    ["failed", "notCompleted"],
    ["mismatch", "problem"],
  ] as const)("%s 는 %s 로 끝난다", (status, result) => {
    expect(toSettledPurchase({ status, grantedPaid: null, grantedBonus: null })).toEqual({ result, grant: null });
  });
});

describe("formatPurchaseGrant", () => {
  it("유료와 보너스를 함께 말한다", () => {
    expect(formatPurchaseGrant({ paid: 9900, bonus: 990 })).toBe("유료 9,900개와 보너스 990개를 받았어요.");
  });

  it("보너스가 없으면 보너스를 말하지 않는다", () => {
    expect(formatPurchaseGrant({ paid: 900, bonus: 0 })).toBe("유료 900개를 받았어요.");
  });
});
