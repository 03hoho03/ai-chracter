import { describe, expect, it } from "vitest";

import { toRefundNotice } from "./refundNotice";

describe("toRefundNotice", () => {
  it("소장한 회원이 없으면 고지하지 않는다", () => {
    expect(toRefundNotice({ buyerCount: 0, amount: 0 }, "이 소설의 화")).toBeUndefined();
  });

  it("소장한 회원 수와 돌려줄 클로버를 말한다", () => {
    expect(toRefundNotice({ buyerCount: 7, amount: 1210 }, "3~5화")).toEqual([
      "노벨에서 3~5화를 소장한 회원이 7명 있어요.",
      "지우면 그 회원들이 쓴 클로버 1,210개를 자동으로 돌려드리고, 지운 화는 더 볼 수 없게 돼요.",
    ]);
  });
});
