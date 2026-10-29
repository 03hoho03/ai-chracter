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

/** 출석판과 같은 순간 이용약관·환불정책 새 게시본이 시행된다. 꺼진 동안은 지금 게시본, 켜지면 새 게시본과 짝이라 두 벌을
 * 글자 그대로 고정한다. */
describe("정책 문장 — 출석판", () => {
  it("꺼져 있으면 유효기간 안내는 지금 문장 그대로다", () => {
    const sentences = formatValiditySentences(POLICY, false);
    expect(sentences[1]).toBe("미션으로 받은 클로버는 지급일 자정 기준으로 7~8일 뒤 소멸돼요.");
    expect(sentences[3]).toBe("본인인증 기능이 열리면, 미션 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.");
  });

  it("켜져 있으면 유효기간 안내는 새 게시본의 문장이다", () => {
    const sentences = formatValiditySentences(POLICY, true);
    expect(sentences[1]).toBe("미션과 출석으로 받은 클로버는 받은 날부터 7일 동안 쓸 수 있어요.");
    expect(sentences[3]).toBe("미션 클로버와 출석 클로버는 휴대폰 본인인증을 마친 회원에게만 지급돼요.");
  });

  it("두 벌로 나누지 않는 문장은 켜짐과 꺼짐이 같다", () => {
    const off = formatValiditySentences(POLICY, false);
    const on = formatValiditySentences(POLICY, true);
    expect(on[0]).toBe(off[0]);
    expect(on[2]).toBe(off[2]);
  });

  it("켜져 있으면 결제 전에 써 볼 수 있다는 문장은 출석 클로버를 말한다", () => {
    expect(formatRefundSentences(POLICY, true, 0, true)[3]).toBe(
      "본인인증을 마친 회원은 결제하기 전에 미션 클로버와 출석 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
  });

  it("꺼져 있으면 결제 전에 써 볼 수 있다는 문장은 지금 그대로다", () => {
    expect(formatRefundSentences(POLICY, true, 15, false)[3]).toBe(
      "본인인증을 마친 회원은 결제하기 전에 하루 15턴의 무료 대화와 미션 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
  });
});
