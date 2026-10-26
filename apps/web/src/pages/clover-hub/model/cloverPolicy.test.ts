import { describe, expect, it } from "vitest";

import { formatRefundSentences, formatValiditySentences } from "./cloverPolicy";

// 실제 정책과 다른 값을 써서, 문장이 받은 숫자를 그대로 쓰는지(웹에 적힌 사본이 아닌지) 가른다.
const POLICY = { purchaseValidityYears: 3, fullRefundDays: 14, reducedRefundPercent: 80 };

describe("정책 문장", () => {
  it("유효기간 햇수는 받은 값을 쓴다", () => {
    expect(formatValiditySentences(POLICY)[0]).toContain("구매일로부터 3년 동안");
  });

  it("전액 환불 날수와 그 뒤 환불 비율은 받은 값을 쓴다", () => {
    const [full, reduced] = formatRefundSentences(POLICY, false, 7);
    expect(full).toContain("결제일로부터 14일 안에는");
    expect(reduced).toContain("14일이 지나도");
    expect(reduced).toContain("그 금액의 80%를");
  });

  it("결제 전에 써 볼 수 있다는 문장에 받은 무료 대화 수를 싣는다", () => {
    expect(formatRefundSentences(POLICY, false, 7).join(" ")).toContain("하루 7턴의 무료 대화");
  });
});
