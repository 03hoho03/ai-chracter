import { describe, expect, it } from "vitest";

import type { EnabledFeature } from "@/entities/session";

import { isStudioNovelAreaVisible } from "./studioNovelArea";

describe("isStudioNovelAreaVisible", () => {
  it("소설화가 열린 계정에만 소설 영역을 보인다", () => {
    expect(isStudioNovelAreaVisible(["novelize"])).toBe(true);
    expect(isStudioNovelAreaVisible(["chat_premium_models", "novelize"])).toBe(true);
  });

  it("소설화가 없는 계정은 다른 기능이 열려 있어도 숨긴다", () => {
    expect(isStudioNovelAreaVisible([])).toBe(false);
    expect(isStudioNovelAreaVisible(["creator_payout", "novelize_premium_models"])).toBe(false);
  });

  it("허용 기능 필드가 없는 옛 /me 응답과 아직 못 읽은 세션은 닫힌 것으로 본다", () => {
    const oldMeResponse: { enabledFeatures?: EnabledFeature[] } = {};
    expect(isStudioNovelAreaVisible(oldMeResponse.enabledFeatures)).toBe(false);
    expect(isStudioNovelAreaVisible(undefined)).toBe(false);
  });
});
