import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { serverToForm } from "./serverToForm";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];

function baseDraftResponse(): StoryDraftResponse {
  return {
    id: "content-1",
    type: "story",
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
        endings: [],
      },
    ],
    keywordNotes: [
      { id: "note-1", infoText: "밤에는 늑대 울음소리가 들린다.", triggerKeywords: ["밤", "늑대"], startingSetupId: "setup-1" },
    ],
    shortcuts: [
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ],
    description: "표류한 선원들의 생존기",
    genreId: "genre-adventure",
    target: "all",
    hashtags: ["모험"],
    visibility: "public",
  };
}

describe("serverToForm", () => {
  it("maps a StoryDraftResponse into form defaultValues", () => {
    expect(serverToForm(baseDraftResponse())).toEqual({
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
      keywordNotes: [
        {
          id: "note-1",
          content: "밤에는 늑대 울음소리가 들린다.",
          triggerKeywords: ["밤", "늑대"],
          scope: { kind: "startingSetup", startingSetupId: "setup-1" },
        },
      ],
      shortcuts: [
        { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
      ],
      registration: {
        description: "표류한 선원들의 생존기",
        genre: "genre-adventure",
        target: "all",
        hashtags: ["모험"],
        visibility: "public",
      },
    });
  });

  it("maps a null thumbnail and null storySetting text fields to a null image / unset form fields", () => {
    const data = baseDraftResponse();
    data.thumbnailAssetId = null;
    data.settingText = null;
    data.developmentExample = null;
    data.customPrompt = null;

    const form = serverToForm(data);

    expect(form.profile.image).toBeNull();
    expect(form.storySetting.worldSetting).toBeUndefined();
    expect(form.storySetting.developmentExample).toBeUndefined();
    expect(form.storySetting.customPrompt).toBeUndefined();
  });

  it("restores an unselected draft's null genre/target as-is", () => {
    const data = baseDraftResponse();
    data.genreId = null;
    data.target = null;

    const form = serverToForm(data);

    expect(form.registration.genre).toBeNull();
    expect(form.registration.target).toBeNull();
  });

  it("restores a custom-template draft's settingText/developmentExample values even though they're unvalidated", () => {
    const data = baseDraftResponse();
    data.promptTemplate = "custom";
    data.customPrompt = "커스텀 프롬프트 본문";

    const form = serverToForm(data);

    expect(form.storySetting.promptTemplate).toBe("custom");
    expect(form.storySetting.worldSetting).toBe("근미래 해양 도시");
    expect(form.storySetting.customPrompt).toBe("커스텀 프롬프트 본문");
  });

  it("maps a null openingMessage/playguide/unit to unset form fields", () => {
    const data = baseDraftResponse();
    const [setup] = data.startingSetups;
    setup!.openingMessage = null;
    setup!.playguide = null;
    setup!.statDefs[0]!.unit = null;

    const form = serverToForm(data);

    expect(form.startingSetups[0]!.openingSituation).toBeUndefined();
    expect(form.startingSetups[0]!.playGuide).toBeUndefined();
    expect(form.startingSetups[0]!.stats[0]!.unit).toBeUndefined();
  });

  it("preserves startingSetups/statDefs array order as returned by the server (no explicit order field)", () => {
    const data = baseDraftResponse();
    const [firstSetup] = data.startingSetups;
    const [firstStat] = firstSetup!.statDefs;
    data.startingSetups = [
      { ...firstSetup!, id: "second", name: "second" },
      { ...firstSetup!, id: "first", name: "first" },
    ];
    data.startingSetups[0]!.statDefs = [
      { ...firstStat!, id: "stat-b" },
      { ...firstStat!, id: "stat-a" },
    ];

    const form = serverToForm(data);

    expect(form.startingSetups.map((setup) => setup.id)).toEqual(["second", "first"]);
    expect(form.startingSetups[0]!.stats.map((stat) => stat.id)).toEqual(["stat-b", "stat-a"]);
  });

  it("maps a null startingSetupId to a global keyword note scope", () => {
    const data = baseDraftResponse();
    data.keywordNotes = [{ ...data.keywordNotes[0]!, startingSetupId: null }];

    const form = serverToForm(data);

    expect(form.keywordNotes[0]!.scope).toEqual({ kind: "global" });
  });

  it("round-trips formToServer(serverToForm(response)) back to the same profile/storySetting/startingSetups/keywordNotes/shortcuts/registration fields", () => {
    const response = baseDraftResponse();

    const payload = formToServer(serverToForm(response));

    expect(payload.name).toBe(response.name);
    expect(payload.thumbnailAssetId).toBe(response.thumbnailAssetId);
    expect(payload.promptTemplate).toBe(response.promptTemplate);
    expect(payload.settingText).toBe(response.settingText);
    expect(payload.developmentExample).toBe(response.developmentExample);
    expect(payload.customPrompt).toBe(response.customPrompt);
    expect(payload.startingSetups).toEqual(
      response.startingSetups.map(({ endings: _endings, ...rest }) => rest),
    );
    expect(payload.keywordNotes).toEqual(response.keywordNotes);
    expect(payload.shortcuts).toEqual(response.shortcuts);
    expect(payload.genreId).toBe(response.genreId);
    expect(payload.target).toBe(response.target);
    expect(payload.hashtags).toEqual(response.hashtags);
    expect(payload.visibility).toBe(response.visibility);
  });
});
