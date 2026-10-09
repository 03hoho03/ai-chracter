import { describe, expect, it } from "vitest";

import { formatTrialSentence } from "./trialSentence";

describe("formatTrialSentence", () => {
  // 게이트가 꺼진 동안은 아무도 인증할 필요가 없다 — 인증 조건을 말하면 거짓이다.
  it("게이트가 꺼져 있으면 본인인증 조건을 말하지 않는다", () => {
    expect(formatTrialSentence(false)).not.toContain("본인인증");
  });

  it("게이트가 켜져 있으면 본인인증한 회원으로 묶는다", () => {
    expect(formatTrialSentence(true)).toContain("본인인증을 마친 회원은");
  });
});
