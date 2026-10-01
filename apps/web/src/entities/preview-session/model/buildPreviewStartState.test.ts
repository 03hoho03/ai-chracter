import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { loadMediaTagCases } from "@/entities/media-book/@x/preview-session";

import { buildPreviewStartState, PREVIEW_OPENING_MESSAGE_ID } from "./buildPreviewStartState";

const {
  cells: CELLS,
  minaClassroom: MINA_CLASSROOM,
  minaRooftop: MINA_ROOFTOP,
  normalizeCases: NORMALIZE_CASES,
} = loadMediaTagCases();

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

  // 첫 메시지 속 미디어 북 태그는 실채팅에서 서버가 하는 정규화를 여기서 한다 — 같은 입력 표로 서버와 같은 결과인지 본다.
  describe("opening media tags", () => {
    const PERSON_MINA = "11111111-0000-0000-0000-000000000001";
    const SCENE_CLASSROOM = "22222222-0000-0000-0000-000000000001";
    const SCENE_ROOFTOP = "22222222-0000-0000-0000-000000000002";
    const IMAGE = { url: "blob:classroom", width: 768, height: 1024 };

    function mediaBook(): NonNullable<StoryDraftPayload["mediaBook"]> {
      const sceneIdByName = new Map([
        ["교실", SCENE_CLASSROOM],
        ["옥상", SCENE_ROOFTOP],
      ]);
      return {
        people: [{ id: PERSON_MINA, name: "민아" }],
        scenes: [...sceneIdByName].map(([name, id]) => ({ id, name })),
        cells: CELLS.map((cell) => ({
          id: cell.cellId,
          personId: PERSON_MINA,
          sceneId: sceneIdByName.get(cell.scene) ?? "",
          imageAssetId: "33333333-0000-0000-0000-000000000001",
          situationDescription: "",
          unlockHint: "",
          excludeFromChat: false,
        })),
      };
    }

    function openingOf(text: string, overrides: Partial<StoryDraftPayload> = {}) {
      return buildPreviewStartState(
        undefined,
        storyPayload({ startingSetups: [startingSetup({ openingMessage: text })], mediaBook: mediaBook(), ...overrides }),
        { [MINA_CLASSROOM]: IMAGE },
      );
    }

    it.each(NORMALIZE_CASES)("normalizes like the server: %s", (_id, text, expectedText) => {
      expect(openingOf(text).messages[0]?.content).toBe(expectedText);
    });

    it("maps only the cells the opening points at that have an image", () => {
      const state = openingOf("{{img::민아/교실}}\n\n{{img::민아/옥상}}");
      expect(state.openingMediaTagImages).toEqual({ [MINA_CLASSROOM]: IMAGE });
      expect(state.messages[0]?.content).toContain(`{{img::${MINA_ROOFTOP}}}`);
    });

    it("deletes every tag when the payload carries no media book", () => {
      const state = openingOf("앞\n\n{{img::민아/교실}}\n\n뒤", { mediaBook: undefined });
      expect(state.messages[0]?.content).toBe("앞\n\n뒤");
      expect(state.openingMediaTagImages).toEqual({});
    });

    it("leaves a character intro untouched", () => {
      const state = buildPreviewStartState(undefined, characterPayload({ intro: "{{img::민아/교실}}" }), {
        [MINA_CLASSROOM]: IMAGE,
      });
      expect(state.messages[0]?.content).toBe("{{img::민아/교실}}");
      expect(state.openingMediaTagImages).toEqual({});
    });
  });

  // 세션 전 화면은 렌더마다 이 함수로 다시 만들어진다. 첫 메시지 id 가 매번 바뀌면 그 id 를 key 로 쓰는 첫 메시지
  // (그림 포함)가 통째로 다시 마운트된다.
  it("gives the opening message the same id on every call, session or not", () => {
    const first = buildPreviewStartState(undefined, storyPayload());
    const again = buildPreviewStartState(undefined, storyPayload());
    const started = buildPreviewStartState("session-1", storyPayload());
    const character = buildPreviewStartState(undefined, characterPayload());

    expect(first.messages[0]?.id).toBe(PREVIEW_OPENING_MESSAGE_ID);
    expect(again.messages[0]?.id).toBe(PREVIEW_OPENING_MESSAGE_ID);
    expect(started.messages[0]?.id).toBe(PREVIEW_OPENING_MESSAGE_ID);
    expect(character.messages[0]?.id).toBe(PREVIEW_OPENING_MESSAGE_ID);
  });

  // 서버가 주는 응답 메시지 id 는 UUID 다 — 고정 id 가 그 꼴이 아니어야 세션 뒤 메시지와 key 가 겹치지 않는다.
  it("uses an opening id that cannot collide with server message UUIDs", () => {
    expect(PREVIEW_OPENING_MESSAGE_ID).not.toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  });
});
