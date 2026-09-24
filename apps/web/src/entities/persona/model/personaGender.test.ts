import { describe, expect, it } from "vitest";

import { PERSONA_GENDER_LABEL } from "./personaGender";

describe("PERSONA_GENDER_LABEL", () => {
  // persona-goal-prompt.md UP-4 — 화면 라벨은 BE `format_user_persona`가 프롬프트에 쓰는 성별 텍스트와
  // 같은 낱말이다(유저가 고른 말이 그대로 캐릭터에게 전달된다고 읽히게).
  it("남성·여성 두 값을 한국어 라벨로 옮긴다", () => {
    expect(PERSONA_GENDER_LABEL).toEqual({ male: "남성", female: "여성" });
  });
});
