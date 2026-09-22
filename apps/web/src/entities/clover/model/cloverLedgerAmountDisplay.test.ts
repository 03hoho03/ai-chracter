import { describe, expect, it } from "vitest";

import { formatCloverLedgerAmount } from "./cloverLedgerAmountDisplay";

describe("formatCloverLedgerAmount", () => {
  it("양수는 +로 표시한다", () => {
    expect(formatCloverLedgerAmount(100)).toBe("+100");
  });

  it("음수는 −로 표시하고 절댓값을 보여준다", () => {
    expect(formatCloverLedgerAmount(-30)).toBe("-30");
  });

  it("0은 부호 없이 보여준다", () => {
    expect(formatCloverLedgerAmount(0)).toBe("0");
  });

  it("천 단위 구분자를 붙인다", () => {
    expect(formatCloverLedgerAmount(1234)).toBe("+1,234");
  });
});
