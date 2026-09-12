import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { buildPreviewStartState } from "./buildPreviewStartState";

type CharacterDraftPayload = components["schemas"]["CharacterDraftPayload"];
type StoryDraftPayload = components["schemas"]["StoryDraftPayload"];
type StartingSetupDraftItem = components["schemas"]["StartingSetupDraftItem"];
type StatDefDraftItem = components["schemas"]["StatDefDraftItem"];

function characterPayload(overrides: Partial<CharacterDraftPayload> = {}): CharacterDraftPayload {
  return {
    name: "여름밤의 소녀",
    oneLiner: "한줄소개",
    thumbnailAssetId: null,
    intro: "안녕하세요, 반가워요.",
    exampleDialogues: [],
    characterPrompt: "친근한 말투를 쓴다",
    playguide: null,
    situationalImages: [],
    description: "설명",
    genreId: null,
    target: null,
    hashtags: [],
    visibility: "private",
    ...overrides,
  };
}

function statDef(overrides: Partial<StatDefDraftItem> = {}): StatDefDraftItem {
  return {
    id: "stat-1",
    name: "체력",
    icon: "heart",
    color: "rose",
    minValue: 0,
    maxValue: 100,
    initialValue: 80,
    unit: "pt",
    description: "생존에 필요한 신체 상태",
    ...overrides,
  };
}

function startingSetup(overrides: Partial<StartingSetupDraftItem> = {}): StartingSetupDraftItem {
  return {
    id: "setup-1",
    name: "표류 첫날",
    prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다.",
    openingMessage: "파도 소리만 들린다.",
    playguide: null,
    suggestedReplies: ["주변을 둘러본다"],
    statDefs: [statDef()],
    endings: [],
    ...overrides,
  };
}

function storyPayload(overrides: Partial<StoryDraftPayload> = {}): StoryDraftPayload {
  return {
    name: "여름밤의 항해",
    oneLiner: "바다 위 표류기",
    thumbnailAssetId: null,
    promptTemplate: "basic",
    settingText: "근미래 해양 도시",
    customPrompt: null,
    developmentExamples: [],
    userGoal: null,
    rules: null,
    startingSetups: [startingSetup()],
    keywordNotes: [],
    shortcuts: [
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ],
    description: "설명",
    genreId: null,
    target: null,
    hashtags: [],
    visibility: "private",
    ...overrides,
  };
}

describe("buildPreviewStartState", () => {
  it("previewSessionId가 undefined면 결과에도 undefined를 그대로 옮긴다 — 지연 시작의 로컬 플레이스홀더", () => {
    const state = buildPreviewStartState(undefined, characterPayload());

    expect(state.previewSessionId).toBeUndefined();
  });

  it("previewSessionId가 주어지면 결과에 그대로 옮긴다 — 실제 세션 시작 응답 경로", () => {
    const state = buildPreviewStartState("session-1", characterPayload());

    expect(state.previewSessionId).toBe("session-1");
  });

  it("캐릭터 payload는 intro를 첫 메시지로 삼고 스탯·단축어·엔딩 관련 필드는 전부 빈 상태다", () => {
    const state = buildPreviewStartState(undefined, characterPayload({ intro: "오랜만이에요." }));

    expect(state.contentType).toBe("character");
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({ role: "assistant", content: "오랜만이에요." });
    expect(state.stats).toEqual({});
    expect(state.statDefs).toEqual([]);
    expect(state.shortcuts).toEqual([]);
    expect(state.suggestedReplies).toEqual([]);
    expect(state.endingStatus).toEqual({ reached: false, epilogue: undefined });
    expect(state.turnCount).toBe(0);
  });

  it("스토리 payload는 첫 startingSetup의 openingMessage를 첫 메시지로 쓴다", () => {
    const state = buildPreviewStartState(
      undefined,
      storyPayload({ startingSetups: [startingSetup({ openingMessage: "파도 소리만 들린다." })] }),
    );

    expect(state.contentType).toBe("story");
    expect(state.messages[0]).toMatchObject({ role: "assistant", content: "파도 소리만 들린다." });
  });

  it("openingMessage가 비어 있으면 prologue로 대체한다", () => {
    const state = buildPreviewStartState(
      undefined,
      storyPayload({
        startingSetups: [startingSetup({ openingMessage: "", prologue: "배가 좌초되고 눈을 뜨니 낯선 해변이다." })],
      }),
    );

    expect(state.messages[0]?.content).toBe("배가 좌초되고 눈을 뜨니 낯선 해변이다.");
  });

  it("statDefs의 id→initialValue로 stats 초기값을 만들고, statDef 자체도 PreviewStatDef 모양으로 옮긴다", () => {
    const state = buildPreviewStartState(
      undefined,
      storyPayload({
        startingSetups: [startingSetup({ statDefs: [statDef({ id: "hp", initialValue: 80 })] })],
      }),
    );

    expect(state.stats).toEqual({ hp: 80 });
    expect(state.statDefs).toEqual([
      { id: "hp", name: "체력", icon: "heart", color: "rose", min: 0, max: 100, initial: 80, unit: "pt", description: "생존에 필요한 신체 상태" },
    ]);
  });

  it("suggestedReplies는 선택된 startingSetup의 것을 그대로 옮긴다", () => {
    const state = buildPreviewStartState(
      undefined,
      storyPayload({ startingSetups: [startingSetup({ suggestedReplies: ["주변을 둘러본다", "동료를 부른다"] })] }),
    );

    expect(state.suggestedReplies).toEqual(["주변을 둘러본다", "동료를 부른다"]);
  });

  it("startingSetups가 비어 있으면 메시지·스탯 없이 payload 레벨 shortcuts만 옮긴다", () => {
    const state = buildPreviewStartState(undefined, storyPayload({ startingSetups: [] }));

    expect(state.messages).toEqual([]);
    expect(state.stats).toEqual({});
    expect(state.statDefs).toEqual([]);
    expect(state.suggestedReplies).toEqual([]);
    expect(state.shortcuts).toEqual([
      { id: "shortcut-1", name: "회상", description: "과거 회상 장면 삽입", prompt: "회상 장면을 묘사해줘" },
    ]);
  });

  it("두 번째 이후 startingSetups는 무시하고 항상 첫 번째만 결정적으로 고른다", () => {
    const state = buildPreviewStartState(
      undefined,
      storyPayload({
        startingSetups: [
          startingSetup({ id: "setup-1", openingMessage: "첫 시작" }),
          startingSetup({ id: "setup-2", openingMessage: "둘째 시작" }),
        ],
      }),
    );

    expect(state.messages[0]?.content).toBe("첫 시작");
  });
});
