import { describe, expect, it } from "vitest";

import { formatPayoutRate } from "./payoutRate";

describe("formatPayoutRate", () => {
  it("만분율을 퍼센트로 바꾼다", () => {
    expect(formatPayoutRate(500)).toBe("5%");
    expect(formatPayoutRate(10000)).toBe("100%");
  });

  // 서버 설정이 정수 퍼센트가 아닐 수 있다 — 반올림하면 정책과 다른 비율을 말한다.
  it("소수가 있으면 그대로 보인다", () => {
    expect(formatPayoutRate(750)).toBe("7.5%");
    expect(formatPayoutRate(333)).toBe("3.33%");
  });
});
