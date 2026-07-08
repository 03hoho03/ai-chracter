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
    startingSetups: [
      {
        id: "setup-1",
        name: "표류 첫날",
        prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
        openingSituation: "파도 소리만 들린다.",
        playGuide: "생존에 집중하는 톤을 유지하세요.",
        suggestedReplies: ["주변을 둘러본다"],
        stats: [
          {
            id: "stat-1",
            name: "체력",
            icon: "heart",
            color: "rose",
            min: 0,
            max: 100,
            initial: 80,
            unit: "pt",
            description: "생존에 필요한 신체 상태",
          },
        ],
      },
    ],
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
  it("maps profile/storySetting/startingSetups/registration into the StoryDraftPayload shape", () => {
    expect(formToServer(baseFormValues())).toEqual({
      name: "여름밤의 항해",
      oneLiner: "바다 위 표류기",
      thumbnailAssetId: "asset-thumbnail",
      promptTemplate: "basic",
      settingText: "근미래 해양 도시",
      developmentExample: "폭풍우로 배가 좌초된다",
      customPrompt: null,
      startingSetups: [
        {
          id: "setup-1",
          name: "표류 첫날",
          prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
          openingMessage: "파도 소리만 들린다.",
          playguide: "생존에 집중하는 톤을 유지하세요.",
          suggestedReplies: ["주변을 둘러본다"],
          statDefs: [
            {
              id: "stat-1",
              name: "체력",
              icon: "heart",
              color: "rose",
              minValue: 0,
              maxValue: 100,
              initialValue: 80,
              unit: "pt",
              description: "생존에 필요한 신체 상태",
            },
          ],
        },
      ],
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

  it("maps unset openingSituation/playGuide/unit to null", () => {
    const values = baseFormValues();
    const [setup] = values.startingSetups;
    setup!.openingSituation = undefined;
    setup!.playGuide = undefined;
    setup!.stats[0]!.unit = undefined;

    const payload = formToServer(values);

    expect(payload.startingSetups[0]!.openingMessage).toBeNull();
    expect(payload.startingSetups[0]!.playguide).toBeNull();
    expect(payload.startingSetups[0]!.statDefs[0]!.unit).toBeNull();
  });

  it("preserves startingSetups/statDefs array order as the wire's implicit order (no explicit order field)", () => {
    const values = baseFormValues();
    const [firstSetup] = values.startingSetups;
    const [firstStat] = firstSetup!.stats;
    values.startingSetups = [
      { ...firstSetup!, id: "second", name: "second" },
      { ...firstSetup!, id: "first", name: "first" },
    ];
    values.startingSetups[0]!.stats = [
      { ...firstStat!, id: "stat-b" },
      { ...firstStat!, id: "stat-a" },
    ];

    const payload = formToServer(values);

    expect(payload.startingSetups.map((setup) => setup.id)).toEqual(["second", "first"]);
    expect(payload.startingSetups[0]!.statDefs.map((stat) => stat.id)).toEqual(["stat-b", "stat-a"]);
  });
});
