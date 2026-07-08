import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import type { StoryBuilderFormValues } from "./schema";

function baseFormValues(): StoryBuilderFormValues {
  return {
    profile: { name: "여름밤의 항해", oneLiner: "바다 위 표류기", image: { assetId: "asset-thumbnail" } },
    storySetting: {
      promptTemplate: "basic",
      worldSetting: "근미래 해양 도시",
      developmentExample: "폭풍우로 배가 좌초된다",
      customPrompt: undefined,
    },
    registration: {
      description: "표류한 선원들의 생존기",
      genre: "genre-adventure",
      target: "all",
      hashtags: ["모험"],
      visibility: "public",
    },
  };
}

describe("formToServer", () => {
  it("maps profile/storySetting/registration into the StoryDraftPayload shape", () => {
    expect(formToServer(baseFormValues())).toEqual({
      name: "여름밤의 항해",
      oneLiner: "바다 위 표류기",
      thumbnailAssetId: "asset-thumbnail",
      promptTemplate: "basic",
      settingText: "근미래 해양 도시",
      developmentExample: "폭풍우로 배가 좌초된다",
      customPrompt: null,
      description: "표류한 선원들의 생존기",
      genreId: "genre-adventure",
      target: "all",
      hashtags: ["모험"],
      visibility: "public",
    });
  });

  it("maps a null profile image and unset optional storySetting fields to null", () => {
    const values = baseFormValues();
    values.profile.image = null;
    values.storySetting.developmentExample = undefined;

    const payload = formToServer(values);

    expect(payload.thumbnailAssetId).toBeNull();
    expect(payload.developmentExample).toBeNull();
  });

  it("preserves worldSetting/developmentExample values even when promptTemplate is custom", () => {
    const values = baseFormValues();
    values.storySetting = {
      promptTemplate: "custom",
      worldSetting: "남겨둔 이전 세계관 텍스트",
      developmentExample: "남겨둔 전개 예시",
      customPrompt: "커스텀 프롬프트 본문",
    };

    const payload = formToServer(values);

    expect(payload.promptTemplate).toBe("custom");
    expect(payload.settingText).toBe("남겨둔 이전 세계관 텍스트");
    expect(payload.developmentExample).toBe("남겨둔 전개 예시");
    expect(payload.customPrompt).toBe("커스텀 프롬프트 본문");
  });

  it("maps a null selected genre/target as-is", () => {
    const values = baseFormValues();
    values.registration.genre = null;
    values.registration.target = null;

    const payload = formToServer(values);

    expect(payload.genreId).toBeNull();
    expect(payload.target).toBeNull();
  });
});
