import { describe, expect, it } from "vitest";

import { formatRefundSentences, formatValiditySentences } from "./cloverPolicy";

// 실제 정책과 다른 값을 써서, 문장이 받은 숫자를 그대로 쓰는지(웹에 적힌 사본이 아닌지) 가른다.
const POLICY = { purchaseValidityYears: 3, fullRefundDays: 14, reducedRefundPercent: 80 };

describe("정책 문장", () => {
  it("유효기간 햇수는 받은 값을 쓴다", () => {
    expect(formatValiditySentences(POLICY)[0]).toContain("구매일로부터 3년 동안");
  });

  it("전액 환불 날수와 그 뒤 환불 비율은 받은 값을 쓴다", () => {
    const [full, reduced] = formatRefundSentences(POLICY);
    expect(full).toContain("결제일로부터 14일 안에는");
    expect(reduced).toContain("14일이 지나도");
    expect(reduced).toContain("그 금액의 80%를");
  });
});

/** 이 문장들은 이용약관·환불정책 게시본의 같은 문장과 짝이라 글자 그대로 고정한다. 출석판 스위치나 무료 대화 수를 읽지
 * 않고도 출석 클로버를 말하는 문장이어야 한다. */
describe("정책 문장 — 출석 클로버", () => {
  it("유효기간 안내는 미션과 출석으로 받은 클로버를 말한다", () => {
    const sentences = formatValiditySentences(POLICY);
    expect(sentences[1]).toBe("미션과 출석으로 받은 클로버는 받은 날부터 7일 동안 쓸 수 있어요.");
    expect(sentences[3]).toBe("미션 클로버와 출석 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.");
  });

  it("결제 전에 써 볼 수 있다는 문장은 출석 클로버를 말한다", () => {
    expect(formatRefundSentences(POLICY)[3]).toBe(
      "본인인증을 마친 회원은 결제하기 전에 미션 클로버와 출석 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
  });

  it("어느 문장도 무료 대화를 말하지 않는다", () => {
    const all = [...formatValiditySentences(POLICY), ...formatRefundSentences(POLICY)].join(" ");
    expect(all).not.toContain("무료 대화");
  });
});
