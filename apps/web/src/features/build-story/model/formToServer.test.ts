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
            perTurnDelta: -1,
          },
        ],
        endings: [],
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
              perTurnDelta: -1,
            },
          ],
          endings: [],
        },
      ],
      keywordNotes: [
        {
          id: "note-1",
          infoText: "밤에는 늑대 울음소리가 들린다.",
          triggerKeywords: ["밤", "늑대"],
          startingSetupId: "setup-1",
        },
      ],
      shortcuts: [
        { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
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

  it("maps a global keyword note scope to a null startingSetupId", () => {
    const values = baseFormValues();
    values.keywordNotes = [{ ...values.keywordNotes[0]!, scope: { kind: "global" } }];

    const payload = formToServer(values);

    expect(payload.keywordNotes[0]!.startingSetupId).toBeNull();
  });

  it("maps a startingSetup keyword note scope to its startingSetupId", () => {
    const values = baseFormValues();
    values.keywordNotes = [
      { ...values.keywordNotes[0]!, scope: { kind: "startingSetup", startingSetupId: "setup-9" } },
    ];

    const payload = formToServer(values);

    expect(payload.keywordNotes[0]!.startingSetupId).toBe("setup-9");
  });

  it("passes shortcuts through unchanged", () => {
    const payload = formToServer(baseFormValues());

    expect(payload.shortcuts).toEqual([
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ]);
  });

  it("maps an ending's rule tree (single rule + group) into the wire shape, including the operator rename", () => {
    const values = baseFormValues();
    values.startingSetups[0]!.endings = [
      {
        id: "ending-1",
        name: "함께 살아남기",
        turnGate: 12,
        judgePrompt: "주인공들이 서로를 구조했는지 판정",
        statRules: [
          { kind: "rule", id: "rule-1", statId: "stat-1", operator: ">=", value: 50, nextOp: "and" },
          {
            kind: "group",
            id: "group-1",
            nextOp: null,
            rules: [
              { kind: "rule", id: "rule-2", statId: "stat-2", operator: "<", value: 10, nextOp: "or" },
              { kind: "rule", id: "rule-3", statId: "stat-3", operator: "==", value: 3, nextOp: null },
            ],
          },
        ],
        epilogue: "두 사람은 무사히 구조되었다.",
        hint: "체력과 신뢰를 함께 관리하세요.",
      },
    ];

    const payload = formToServer(values);

    expect(payload.startingSetups[0]!.endings).toEqual([
      {
        id: "ending-1",
        name: "함께 살아남기",
        turnCountGate: 12,
        judgmentPrompt: "주인공들이 서로를 구조했는지 판정",
        epilogue: "두 사람은 무사히 구조되었다.",
        hint: "체력과 신뢰를 함께 관리하세요.",
        statRules: [
          { kind: "rule", id: "rule-1", statId: "stat-1", operator: "gte", threshold: 50, nextOp: "and" },
          {
            kind: "group",
            id: "group-1",
            nextOp: null,
            rules: [
              { kind: "rule", id: "rule-2", statId: "stat-2", operator: "lt", threshold: 10, nextOp: "or" },
              { kind: "rule", id: "rule-3", statId: "stat-3", operator: "eq", threshold: 3, nextOp: null },
            ],
          },
        ],
      },
    ]);
  });

  it("maps unset ending epilogue/hint to null", () => {
    const values = baseFormValues();
    values.startingSetups[0]!.endings = [
      {
        id: "ending-1",
        name: "열린 결말",
        turnGate: 10,
        judgePrompt: "판정 프롬프트",
        statRules: [],
        epilogue: undefined,
        hint: undefined,
      },
    ];

    const payload = formToServer(values);

    expect(payload.startingSetups[0]!.endings[0]!.epilogue).toBeNull();
    expect(payload.startingSetups[0]!.endings[0]!.hint).toBeNull();
  });

  it("preserves endings/statRules array order as the wire's implicit order (no explicit order field)", () => {
    const values = baseFormValues();
    values.startingSetups[0]!.endings = [
      { id: "second", name: "second", turnGate: 10, judgePrompt: "판정", statRules: [] },
      { id: "first", name: "first", turnGate: 10, judgePrompt: "판정", statRules: [] },
    ];
    values.startingSetups[0]!.endings[0]!.statRules = [
      { kind: "rule", id: "rule-b", statId: "stat-1", operator: ">", value: 1, nextOp: null },
      { kind: "rule", id: "rule-a", statId: "stat-1", operator: ">", value: 1, nextOp: null },
    ];

    const payload = formToServer(values);

    expect(payload.startingSetups[0]!.endings.map((ending) => ending.id)).toEqual(["second", "first"]);
    expect(payload.startingSetups[0]!.endings[0]!.statRules.map((rule) => rule.id)).toEqual([
      "rule-b",
      "rule-a",
    ]);
  });
});
