import { describe, expect, it } from "vitest";

import { formatFreeChatSentence } from "./freeChatSentence";

describe("formatFreeChatSentence", () => {
  // 게이트가 꺼진 동안은 누구나 무료 대화를 받는다 — 인증 조건을 말하면 거짓이다.
  it("게이트가 꺼져 있으면 본인인증 조건을 말하지 않는다", () => {
    expect(formatFreeChatSentence(false, 7, 3)).not.toContain("본인인증");
  });

  // 게이트가 켜지면 인증하지 않은 회원의 무료분은 0이다.
  it("게이트가 켜져 있으면 본인인증한 회원으로 묶는다", () => {
    expect(formatFreeChatSentence(true, 7, 3)).toContain("본인인증을 마친 회원은");
  });

  // 무료 대화 수와 단가는 서버 값이다 — 받은 값이 그대로 나와야 다음 가격 변경에서 화면과 서버가 갈리지 않는다.
  it.each([false, true])("무료 대화 수와 단가는 받은 값을 그대로 말한다(게이트 %s)", (gate) => {
    const sentence = formatFreeChatSentence(gate, 7, 3);
    expect(sentence).toContain("하루 7턴까지 무료");
    expect(sentence).toContain("1턴에 클로버 3개");
  });

  // 무료분은 기본 모델 대화에만 있다 — 상위 모델까지 무료로 읽히면 안 된다.
  it.each([false, true])("무료 대상을 기본 모델 대화로 한정한다(게이트 %s)", (gate) => {
    expect(formatFreeChatSentence(gate, 7, 3)).toContain("기본 모델 대화");
  });

  it.each([undefined, 0])("무료 대화 수가 %s 이면 문장을 내지 않는다", (turns) => {
    expect(formatFreeChatSentence(false, turns, 3)).toBeNull();
  });
});
