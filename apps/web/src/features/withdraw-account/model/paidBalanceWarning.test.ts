import { describe, expect, it } from "vitest";

import { getPaidBalanceWarning } from "./paidBalanceWarning";

describe("getPaidBalanceWarning", () => {
  it("유료 잔액이 있으면 그 수로 경고한다", () => {
    expect(getPaidBalanceWarning({ paidCloverBalance: 1_150 })).toEqual({ kind: "count", paidBalance: 1_150 });
  });

  it("유료 잔액이 없으면 경고하지 않는다", () => {
    expect(getPaidBalanceWarning({ paidCloverBalance: 0 })).toEqual({ kind: "none" });
  });

  // 못 읽었다고 경고를 빼면 유료 회원이 환불 안내 없이 떠난다.
  it("세션을 못 읽었으면 숫자 없는 경고다", () => {
    expect(getPaidBalanceWarning(undefined)).toEqual({ kind: "unknown" });
  });
});
