import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { serverToForm } from "./serverToForm";

type StoryDraftResponse = components["schemas"]["StoryDraftResponse"];

function requireFirst<T>(items: readonly T[]): T {
  const [first] = items;
  if (!first) throw new Error("fixture empty");
  return first;
}

function baseDraftResponse(): StoryDraftResponse {
  return {
    id: "content-1",
    type: "story",
    name: "여름밤의 항해",
    oneLiner: "바다 위 표류기",
    thumbnailAssetId: "asset-thumbnail",
    thumbnailUrl: "https://example.com/asset-thumbnail.webp",
    promptTemplate: "basic",
    settingText: "근미래 해양 도시",
    developmentExample: "폭풍우로 배가 좌초된다",
    developmentExamples: [{ userLine: "무슨 일이 있었는지 설명해주세요", assistantLine: "폭풍우로 배가 좌초된다" }],
    userGoal: "표류에서 살아남아 무사히 귀환한다",
    rules: "선원들 앞에서 약한 모습을 보이지 않는다",
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
        developmentExamples: [{ userLine: "무슨 일이 있었는지 설명해주세요", assistantLine: "폭풍우로 배가 좌초된다" }],
        userGoal: "표류에서 살아남아 무사히 귀환한다",
        rules: "선원들 앞에서 약한 모습을 보이지 않는다",
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
    });
  });

  it("maps a null thumbnail and null storySetting text fields to a null image / unset form fields", () => {
    const data = baseDraftResponse();
    data.thumbnailAssetId = null;
    data.settingText = null;
    data.customPrompt = null;
    data.userGoal = null;
    data.rules = null;
    data.developmentExamples = [];

    const form = serverToForm(data);

    expect(form.profile.image).toBeNull();
    expect(form.storySetting.worldSetting).toBeUndefined();
    expect(form.storySetting.customPrompt).toBeUndefined();
    expect(form.storySetting.userGoal).toBeUndefined();
    expect(form.storySetting.rules).toBeUndefined();
    expect(form.storySetting.developmentExamples).toEqual([]);
  });

  it("restores an unselected draft's null genre/target as-is", () => {
    const data = baseDraftResponse();
    data.genreId = null;
    data.target = null;

    const form = serverToForm(data);

    expect(form.registration.genre).toBeNull();
    expect(form.registration.target).toBeNull();
  });

  it("restores a custom-template draft's settingText value even though it's unvalidated", () => {
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
    const setup = requireFirst(data.startingSetups);
    setup.openingMessage = null;
    setup.playguide = null;
    requireFirst(setup.statDefs).unit = null;

    const form = serverToForm(data);

    const firstSetup = requireFirst(form.startingSetups);
    expect(firstSetup.openingSituation).toBeUndefined();
    expect(firstSetup.playGuide).toBeUndefined();
    expect(requireFirst(firstSetup.stats).unit).toBeUndefined();
  });

  it("preserves startingSetups/statDefs array order as returned by the server (no explicit order field)", () => {
    const data = baseDraftResponse();
    const firstSetup = requireFirst(data.startingSetups);
    const firstStat = requireFirst(firstSetup.statDefs);
    data.startingSetups = [
      { ...firstSetup, id: "second", name: "second" },
      { ...firstSetup, id: "first", name: "first" },
    ];
    requireFirst(data.startingSetups).statDefs = [
      { ...firstStat, id: "stat-b" },
      { ...firstStat, id: "stat-a" },
    ];

    const form = serverToForm(data);

    expect(form.startingSetups.map((setup) => setup.id)).toEqual(["second", "first"]);
    expect(requireFirst(form.startingSetups).stats.map((stat) => stat.id)).toEqual(["stat-b", "stat-a"]);
  });

  it("maps a null startingSetupId to a global keyword note scope", () => {
    const data = baseDraftResponse();
    data.keywordNotes = [{ ...requireFirst(data.keywordNotes), startingSetupId: null }];

    const form = serverToForm(data);

    expect(requireFirst(form.keywordNotes).scope).toEqual({ kind: "global" });
  });

  function endingRuleTreeResponse(): StoryDraftResponse["startingSetups"][number]["endings"] {
    return [
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
    ];
  }

  it("maps an ending's rule tree (single rule + group) from the wire shape, including the operator rename", () => {
    const data = baseDraftResponse();
    requireFirst(data.startingSetups).endings = endingRuleTreeResponse();

    const form = serverToForm(data);

    expect(requireFirst(form.startingSetups).endings).toEqual([
      {
        id: "ending-1",
        name: "함께 살아남기",
        turnGate: 12,
        judgePrompt: "주인공들이 서로를 구조했는지 판정",
        epilogue: "두 사람은 무사히 구조되었다.",
        hint: "체력과 신뢰를 함께 관리하세요.",
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
      },
    ]);
  });

  it("maps a null ending epilogue/hint to unset form fields", () => {
    const data = baseDraftResponse();
    requireFirst(data.startingSetups).endings = [
      {
        id: "ending-1",
        name: "열린 결말",
        turnCountGate: 10,
        judgmentPrompt: "판정 프롬프트",
        epilogue: null,
        hint: null,
        statRules: [],
      },
    ];

    const form = serverToForm(data);

    const firstEnding = requireFirst(requireFirst(form.startingSetups).endings);
    expect(firstEnding.epilogue).toBeUndefined();
    expect(firstEnding.hint).toBeUndefined();
  });

  it("preserves endings/statRules array order as returned by the server (no explicit order field)", () => {
    const data = baseDraftResponse();
    const firstSetup = requireFirst(data.startingSetups);
    firstSetup.endings = [
      { id: "second", name: "second", turnCountGate: 10, judgmentPrompt: "판정", epilogue: null, hint: null, statRules: [] },
      { id: "first", name: "first", turnCountGate: 10, judgmentPrompt: "판정", epilogue: null, hint: null, statRules: [] },
    ];
    requireFirst(firstSetup.endings).statRules = [
      { kind: "rule", id: "rule-b", statId: "stat-1", operator: "gt", threshold: 1, nextOp: null },
      { kind: "rule", id: "rule-a", statId: "stat-1", operator: "gt", threshold: 1, nextOp: null },
    ];

    const form = serverToForm(data);

    const firstFormSetup = requireFirst(form.startingSetups);
    expect(firstFormSetup.endings.map((ending) => ending.id)).toEqual(["second", "first"]);
    expect(requireFirst(firstFormSetup.endings).statRules.map((rule) => rule.id)).toEqual(["rule-b", "rule-a"]);
  });

  it("round-trips formToServer(serverToForm(response)) back to the same profile/storySetting/startingSetups (incl. endings/rule trees)/keywordNotes/shortcuts/registration fields", () => {
    const response = baseDraftResponse();
    requireFirst(response.startingSetups).endings = endingRuleTreeResponse();

    const payload = formToServer(serverToForm(response));

    expect(payload.name).toBe(response.name);
    expect(payload.thumbnailAssetId).toBe(response.thumbnailAssetId);
    expect(payload.promptTemplate).toBe(response.promptTemplate);
    expect(payload.settingText).toBe(response.settingText);
    // chat-techspec.md §6-2(D-13): 구 필드는 폼이 더 이상 관리하지 않으므로 아예 안 보낸다(안 보내야
    // 서버가 롤백 안전망인 구 컬럼 값을 그대로 둔다) — formToServer.test.ts의 전용 테스트가 이 계약을
    // 못박는다.
    expect(payload).not.toHaveProperty("developmentExample");
    expect(payload.developmentExamples).toEqual(response.developmentExamples);
    expect(payload.userGoal).toBe(response.userGoal);
    expect(payload.rules).toBe(response.rules);
    expect(payload.customPrompt).toBe(response.customPrompt);
    expect(payload.startingSetups).toEqual(response.startingSetups);
    expect(payload.keywordNotes).toEqual(response.keywordNotes);
    expect(payload.shortcuts).toEqual(response.shortcuts);
    expect(payload.genreId).toBe(response.genreId);
    expect(payload.target).toBe(response.target);
    expect(payload.hashtags).toEqual(response.hashtags);
    expect(payload.visibility).toBe(response.visibility);
  });

  it("round-trips empty userGoal/rules/developmentExamples losslessly (existing 33 contents are all in this state)", () => {
    const response = baseDraftResponse();
    response.userGoal = null;
    response.rules = null;
    response.developmentExamples = [];

    const payload = formToServer(serverToForm(response));

    expect(payload.userGoal).toBeNull();
    expect(payload.rules).toBeNull();
    expect(payload.developmentExamples).toEqual([]);
  });

  it("round-trips up to 3 development example pairs losslessly", () => {
    const response = baseDraftResponse();
    response.developmentExamples = [
      { userLine: "안녕하세요", assistantLine: "어서 오세요" },
      { userLine: "여기 앉아도 될까요", assistantLine: "그럼요, 편히 앉으세요" },
      { userLine: "메뉴 추천해주세요", assistantLine: "오늘의 스튜를 추천해요" },
    ];

    const payload = formToServer(serverToForm(response));

    expect(payload.developmentExamples).toEqual(response.developmentExamples);
  });
});
