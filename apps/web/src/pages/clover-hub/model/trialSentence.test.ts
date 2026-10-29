import { describe, expect, it } from "vitest";

import { formatTrialSentence } from "./trialSentence";

describe("formatTrialSentence", () => {
  // 게이트가 꺼진 동안은 아무도 인증할 필요가 없다 — 인증 조건을 말하면 거짓이다.
  it("게이트가 꺼져 있으면 본인인증 조건을 말하지 않는다", () => {
    expect(formatTrialSentence(false, 7)).not.toContain("본인인증");
  });

  it("게이트가 켜져 있으면 본인인증한 회원으로 묶는다", () => {
    expect(formatTrialSentence(true, 7)).toContain("본인인증을 마친 회원은");
  });

  // 무료 대화 수는 서버 값이다 — 화면에 박아 둔 숫자가 아니라 받은 값이 그대로 나와야 다음 변경에서 어긋나지 않는다.
  it.each([false, true])("무료 대화 수는 받은 값을 그대로 말한다(게이트 %s)", (gate) => {
    const sentence = formatTrialSentence(gate, 7);
    expect(sentence).toContain("하루 7턴의 무료 대화");
    expect(sentence).toContain("미션 클로버");
  });

  // 출석판이 꺼진 동안은 받을 수 없는 지급을 약속하게 되고, 체험 수단으로 "무료 클로버" 일반을 말해도 그렇다.
  it("출석판이 꺼져 있으면 출석이나 막연한 무료 클로버를 체험 수단으로 말하지 않는다", () => {
    for (const gate of [false, true]) {
      const sentence = formatTrialSentence(gate, 7, false);
      expect(sentence).not.toContain("출석");
      expect(sentence).not.toContain("무료 클로버");
    }
  });

  // 새 필드가 없는 옛 응답이나 무료 대화가 0인 경우 — 없는 무료 대화를 약속하지 않는다.
  it.each([undefined, 0])("무료 대화 수가 %s 이면 미션 클로버만 말한다", (turns) => {
    const sentence = formatTrialSentence(false, turns);
    expect(sentence).not.toContain("무료 대화");
    expect(sentence).toContain("미션 클로버로");
  });
});

/** 출석판이 켜지면 하루 무료 대화가 없어지고 출석 보상은 늘 본인인증이 필요하다(결제도 인증이 필요해 "인증한 회원은 결제
 * 전에 써 볼 수 있다" 가 참이다). 그래서 게이트·무료 대화 수와 무관하게 새 게시본과 짝인 한 문장이다. */
describe("formatTrialSentence — 출석판", () => {
  const ON_SENTENCE = "본인인증을 마친 회원은 결제하기 전에 미션 클로버와 출석 클로버로 서비스를 먼저 써 볼 수 있어요.";

  it.each([
    [false, 0],
    [true, 0],
    [false, 15],
    [true, 15],
    [true, undefined],
  ])("켜져 있으면 게이트 %s · 무료 대화 %s 와 무관하게 같은 문장이다", (gate, turns) => {
    expect(formatTrialSentence(gate, turns, true)).toBe(ON_SENTENCE);
  });

  it("꺼져 있으면 지금 문장 그대로다", () => {
    expect(formatTrialSentence(true, 15, false)).toBe(
      "본인인증을 마친 회원은 결제하기 전에 하루 15턴의 무료 대화와 미션 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
    expect(formatTrialSentence(false, 15, false)).toBe(
      "결제하기 전에 하루 15턴의 무료 대화와 미션 클로버로 서비스를 먼저 써 볼 수 있어요.",
    );
    expect(formatTrialSentence(true, 0, false)).toBe("본인인증을 마친 회원은 결제하기 전에 미션 클로버로 서비스를 먼저 써 볼 수 있어요.");
  });
});
