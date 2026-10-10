import { describe, expect, it } from "vitest";

import { chatModelChipName } from "./chatModelChip";

const ON = ["chat_premium_models"] as const;

describe("chatModelChipName", () => {
  it("기능이 켜져 있고 이용제한이 아닌 방이면 방 응답의 모델 이름을 낸다", () => {
    expect(chatModelChipName({ enabledFeatures: ON, isRestricted: false, modelName: "Claude Opus 5.5" })).toBe(
      "Claude Opus 5.5",
    );
  });

  // ⋮ 패널의 「AI 모델」과 같은 판정이다 — 기능이 꺼진 계정에는 칩만 새지 않는다.
  it("기능이 꺼져 있으면 숨긴다", () => {
    expect(chatModelChipName({ enabledFeatures: [], isRestricted: false, modelName: "Gemini" })).toBeUndefined();
    expect(chatModelChipName({ enabledFeatures: ["novelize"], isRestricted: false, modelName: "Gemini" })).toBeUndefined();
  });

  it("이용제한 방이면 숨긴다", () => {
    expect(chatModelChipName({ enabledFeatures: ON, isRestricted: true, modelName: "Gemini" })).toBeUndefined();
  });

  // 이름 칸이 생기기 전의 서버 응답에는 이름이 없다. 기본 모델 이름으로 채우면 상위 모델 방에 거짓 이름이 붙는다.
  it.each([undefined, ""])("이름이 %j 이면 기본 모델 이름으로 채우지 않고 숨긴다", (modelName) => {
    expect(chatModelChipName({ enabledFeatures: ON, isRestricted: false, modelName })).toBeUndefined();
  });
});
