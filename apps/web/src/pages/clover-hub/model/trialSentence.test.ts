import { describe, expect, it } from "vitest";

import { formatTrialSentence } from "./trialSentence";

/** 하루 무료 대화는 없고 출석 보상은 늘 본인인증이 필요하다(결제도 인증이 필요해 "인증한 회원은 결제 전에 써 볼 수 있다" 가
 * 참이다). 그래서 게이트 스위치·무료 대화 수·출석판 스위치를 읽지 않는 한 문장이고, 환불정책 게시본과 짝이라 글자를 고정한다. */
describe("formatTrialSentence", () => {
  it("본인인증한 회원이 미션 클로버와 출석 클로버로 써 볼 수 있다고 말한다", () => {
    expect(formatTrialSentence()).toBe(
      "본인인증을 마친 회원은 결제하기 전에 미션 클로버와 출석 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
  });

  it("무료 대화를 말하지 않는다", () => {
    expect(formatTrialSentence()).not.toContain("무료 대화");
  });
});
