import { describe, expect, it } from "vitest";

import { isLastBatchSold, toNovelHideDescription, toRefundNotice } from "./refundNotice";

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

describe("toNovelHideDescription", () => {
  it("판매된 소설이면 숨긴다고 말하고 소장한 회원 수를 넣는다", () => {
    const description = toNovelHideDescription({ novelSold: true, novelBuyerCount: 1234 });
    expect(description).toContain("1,234명 있어 바로 지우지 않고 숨겨요");
    expect(description).toContain("소장한 회원은 산 화를 계속 읽고");
  });

  it.each([{ novelSold: false, novelBuyerCount: 3 }, undefined])("판매 표시가 없거나 거짓이면 지금 설명 그대로다 (%#)", (preview) => {
    expect(toNovelHideDescription(preview)).toBeUndefined();
  });
});

describe("isLastBatchSold", () => {
  it("판매된 마지막 묶음만 지울 수 없다고 가른다", () => {
    expect(isLastBatchSold({ lastBatchSold: true })).toBe(true);
    expect(isLastBatchSold({ lastBatchSold: false })).toBe(false);
    expect(isLastBatchSold(undefined)).toBe(false);
  });
});
