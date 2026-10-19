import type { components } from "@ai-character-chat/api-types";
import { describe, expect, it } from "vitest";

import { toChatRoomState } from "./toChatRoomState";

const storyRoomBase: Omit<components["schemas"]["ChatRoomResponse"], "contentSnapshot"> = {
  id: "room-2",
  contentId: "story-1",
  contentType: "story",
  name: "대화 1",
  startingSetupId: "setup-1",
  turnCount: 5,
  endingReached: false,
  stats: { "stat-1": 42 },
  messages: [],
  latestVersionAvailable: true,
  versionAutoUpgraded: false,
  contentRestricted: false,
  hasMoreMessagesBefore: false,
  createdAt: "2026-07-08T00:00:00Z",
  updatedAt: "2026-07-08T00:00:00Z",
};

describe("toChatRoomState", () => {
  it("maps the character chat ChatRoomResponse into ChatRoomState with empty story-only fields", () => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      turnCount: 3,
      endingReached: false,
      messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state).toEqual({
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
      openingMediaTagImages: {},
      stats: {},
      endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
      turnCount: 3,
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
      contentRestricted: false,
      novelCreationBlocked: false,
      hasMoreMessagesBefore: false,
      effectiveChatModel: "gemini",
    });
  });

  // 「소설로 보기」를 막을지는 서버가 정해 보낸다. 칸이 없는 응답은 이 칸이 생기기 전의 서버라 막지 않는다.
  it.each([
    ["the server says new novels are blocked", { novelCreationBlocked: true }, true],
    ["the server says they are not", { novelCreationBlocked: false }, false],
    ["an older server sends no such field", {}, false],
  ])("projects novelCreationBlocked when %s", (_, field, expected) => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "story",
      name: "대화 1",
      turnCount: 0,
      endingReached: false,
      messages: [],
      hasMoreMessagesBefore: false,
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
      ...field,
    });

    expect(state.novelCreationBlocked).toBe(expected);
  });

  // 방의 글쓰기 모델과 턴 가격은 응답 값을 그대로 옮긴다 — 화면은 가격의 사본을 두지 않고 이 값으로 잔액 부족과 확인
  // 금액을 정한다.
  it("carries the room's effective chat model and its per-turn clover cost", () => {
    const base = {
      id: "room-1",
      contentId: "content-1",
      contentType: "story" as const,
      name: "대화 1",
      turnCount: 0,
      endingReached: false,
      messages: [],
      hasMoreMessagesBefore: false,
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    };

    const premium = toChatRoomState({
      ...base,
      chatModel: "opus",
      effectiveChatModel: "opus",
      effectiveChatModelName: "Claude Opus 5.5",
      turnCost: 65,
    });
    expect(premium.effectiveChatModel).toBe("opus");
    expect(premium.effectiveChatModelName).toBe("Claude Opus 5.5");
    expect(premium.turnCost).toBe(65);

    // 허용을 거둔 방은 저장값(opus)이 아니라 서버가 정한 유효 모델과 그 가격을 따른다.
    const fallenBack = toChatRoomState({ ...base, chatModel: "opus", effectiveChatModel: "gemini", turnCost: 10 });
    expect(fallenBack.effectiveChatModel).toBe("gemini");
    expect(fallenBack.turnCost).toBe(10);
  });

  // 이 칸들이 생기기 전의 서버는 값을 보내지 않는다. 모델은 서버 기본값과 같은 기본 모델로 채우고, 가격은 비워 둔다 —
  // 화면에 가격 사본을 두지 않기로 해서 지어낼 숫자가 없다.
  it("falls back to the default model and an unknown cost when the server omits them", () => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      turnCount: 0,
      endingReached: false,
      messages: [],
      hasMoreMessagesBefore: false,
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.effectiveChatModel).toBe("gemini");
    expect(state.turnCost).toBeUndefined();
    // 이름은 기본 모델 이름으로 채우지 않는다 — 화면은 이름이 없으면 모델 칩을 그리지 않는다.
    expect(state.effectiveChatModelName).toBeUndefined();
  });

  // 화면이 작가 글의 `{{user}}`·`{{char}}` 를 방의 프로필 이름과 방이 고정한 버전의 작품 이름으로 바꾸려면 두 이름이
  // 방 상태에 있어야 한다. 프로필 없음(서버 null)은 undefined 로 접는다 — 이름 고르기가 대체어로 넘어간다.
  it("carries the names the screen puts in for {{user}} and {{char}}", () => {
    const base: Parameters<typeof toChatRoomState>[0] = {
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      turnCount: 0,
      endingReached: false,
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    };

    expect(
      toChatRoomState({ ...base, personaName: "지훈", contentName: "유나" }),
    ).toMatchObject({ personaName: "지훈", contentName: "유나" });
    expect(toChatRoomState({ ...base, personaName: null })).toMatchObject({
      personaName: undefined,
    });
  });

  // 첫 메시지 속 미디어 북 그림 맵과 판정 이미지 크기는 그대로 옮기고, 서버 `null` 크기는 undefined 로 접는다.
  it("carries the opening media tag images and judged image sizes", () => {
    const image = { url: "https://cdn.example/a.webp", width: 768, height: 1024 };
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "story",
      name: "대화 1",
      turnCount: 1,
      endingReached: false,
      messages: [
        { id: "m1", role: "assistant", content: "열림", createdAt: "2026-07-08T00:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "판정",
          imageId: "cell-1",
          imageUrl: image.url,
          imageWidth: 1200,
          imageHeight: null,
          createdAt: "2026-07-08T00:00:00Z",
        },
      ],
      mediaTagImages: { "cell-1": image },
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.openingMediaTagImages).toEqual({ "cell-1": image });
    expect(state.messages[1]).toMatchObject({ imageWidth: 1200, imageHeight: undefined });
  });

  // 방의 대화 프로필 선택. 서버 `null`(선택 없음)과 필드 부재는 둘 다 undefined다.
  it("carries personaId and folds a null personaId to undefined", () => {
    const base = {
      id: "room-1",
      contentId: "content-1",
      contentType: "character" as const,
      name: "대화 1",
      turnCount: 0,
      endingReached: false,
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    };
    expect(toChatRoomState({ ...base, personaId: "persona-1" }).personaId).toBe("persona-1");
    expect(toChatRoomState({ ...base, personaId: null })).toHaveProperty("personaId", undefined);
  });

  // 되돌릴 수 있는 응답 id. 서버 `null`(되돌릴 답 없음)과 필드 부재(이 칸이 생기기 전의 서버)는 둘 다 undefined다.
  it("carries previousResponseFor and folds null or a missing field to undefined", () => {
    const base = {
      id: "room-1",
      contentId: "content-1",
      contentType: "character" as const,
      name: "대화 1",
      turnCount: 1,
      endingReached: false,
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    };
    expect(toChatRoomState({ ...base, previousResponseFor: "a1-regen" }).previousResponseFor).toBe("a1-regen");
    expect(toChatRoomState({ ...base, previousResponseFor: null })).toHaveProperty("previousResponseFor", undefined);
    expect(toChatRoomState(base).previousResponseFor).toBeUndefined();
  });

  // 이 칸이 생기기 전의 서버는 도달 여부만 보낸다 — 에필로그 없이 도달 표시만 옮긴다(배포가 겹치는 동안의 옛 API).
  it("carries the endingReached flag through into endingStatus.reached without an ending field (older server)", () => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      turnCount: 12,
      endingReached: true,
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.endingStatus).toEqual({ reached: true, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined });
  });

  // 도달한 엔딩은 그 턴의 스트림 이벤트에만 실려 왔다 — 방을 다시 받으면(새로고침·재조회) 에필로그가 사라지지 않도록
  // 방 응답의 엔딩을 이벤트와 같은 자리로 옮긴다. 에필로그 그림은 첫 메시지의 그림 맵과 섞지 않는다.
  it("carries the reached ending's id, epilogue and its images into endingStatus", () => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "story",
      name: "대화 1",
      turnCount: 12,
      endingReached: true,
      ending: {
        endingId: "ending-1",
        epilogue: "끝났다.\n\n{{img::cell-2}}",
        mediaTagImages: { "cell-2": { url: "https://r2.example/epilogue.webp", width: 300, height: null } },
      },
      mediaTagImages: { "cell-1": { url: "https://r2.example/opening.webp", width: 640, height: 480 } },
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.endingStatus).toEqual({
      reached: true,
      endingId: "ending-1",
      reachedAtTurn: undefined,
      epilogue: "끝났다.\n\n{{img::cell-2}}",
      mediaTagImages: { "cell-2": { url: "https://r2.example/epilogue.webp", width: 300, height: undefined } },
    });
    expect(state.openingMediaTagImages).toEqual({
      "cell-1": { url: "https://r2.example/opening.webp", width: 640, height: 480 },
    });
  });

  it("maps a reached ending without an epilogue to an undefined epilogue", () => {
    const state = toChatRoomState({
      id: "room-1",
      contentId: "content-1",
      contentType: "story",
      name: "대화 1",
      turnCount: 12,
      endingReached: true,
      ending: { endingId: "ending-1", epilogue: null },
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.endingStatus).toEqual({
      reached: true,
      endingId: "ending-1",
      reachedAtTurn: undefined,
      epilogue: undefined,
      mediaTagImages: {},
    });
  });

  it("carries whether older messages are still on the server", () => {
    const base = {
      id: "room-1",
      contentId: "content-1",
      contentType: "character" as const,
      name: "대화 1",
      turnCount: 60,
      endingReached: false,
      messages: [],
      latestVersionAvailable: false,
      versionAutoUpgraded: false,
      contentRestricted: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    };
    expect(toChatRoomState({ ...base, hasMoreMessagesBefore: true }).hasMoreMessagesBefore).toBe(true);
    expect(toChatRoomState({ ...base, hasMoreMessagesBefore: false }).hasMoreMessagesBefore).toBe(false);
  });

  it("maps story chat contentSnapshot/stats/startingSetupId from a snapshot without the judgment fields", () => {
    // 서버가 판정 재료(스탯 판정용 설명, 엔딩 판정 문안·에필로그·힌트·규칙)를 지운 응답이다 — 그 키가 없어도 받는다.
    const state = toChatRoomState({
      ...storyRoomBase,
      contentSnapshot: {
        stats: [
          {
            id: "stat-1",
            name: "호감도",
            icon: "❤️",
            color: "#ff4d6d",
            minValue: 0,
            maxValue: 100,
            initialValue: 50,
            unit: null,
            playerDescription: "가까워질수록 오른다",
          },
          {
            id: "stat-2",
            name: "체력",
            icon: "Heart",
            color: "#3366ff",
            minValue: 0,
            maxValue: 10,
            initialValue: 10,
            unit: "칸",
            playerDescription: null,
          },
        ],
        endings: [{ id: "ending-1", name: "해피엔딩", turnCountGate: 10 }],
        shortcuts: [{ id: "shortcut-1", name: "인사", description: "인사하기", prompt: "안녕이라고 인사해줘" }],
        suggestedReplies: ["계속 이야기해줘"],
        pinnedStartingSetupId: "physical-setup-1",
      },
    });

    expect(state.startingSetupId).toBe("setup-1");
    expect(state.stats).toEqual({ "stat-1": 42 });
    expect(state.contentSnapshot).toEqual({
      stats: [
        {
          id: "stat-1",
          name: "호감도",
          icon: "❤️",
          color: "#ff4d6d",
          min: 0,
          max: 100,
          initial: 50,
          unit: undefined,
          playerDescription: "가까워질수록 오른다",
        },
        {
          id: "stat-2",
          name: "체력",
          icon: "Heart",
          color: "#3366ff",
          min: 0,
          max: 10,
          initial: 10,
          unit: "칸",
          playerDescription: undefined,
        },
      ],
      endings: [{ id: "ending-1", name: "해피엔딩", turnGate: 10 }],
      shortcuts: [{ id: "shortcut-1", name: "인사", description: "인사하기", prompt: "안녕이라고 인사해줘" }],
      suggestedReplies: ["계속 이야기해줘"],
      pinnedStartingSetupId: "physical-setup-1",
      // 장면 헤더 칸이 없는 옛 서버 응답은 헤더가 꺼진 방이다.
      sceneHeaderEnabled: false,
    });
  });

  it("carries the scene header switch, the first scene and each message's scene with nulls folded to undefined", () => {
    const state = toChatRoomState({
      ...storyRoomBase,
      messages: [
        { id: "o", role: "assistant", content: "프롤로그", createdAt: "2026-07-08T00:00:00Z", scene: null },
        {
          id: "a1",
          role: "assistant",
          content: "대사",
          createdAt: "2026-07-08T00:01:00Z",
          scene: { place: "갱도", time: null },
        },
      ],
      contentSnapshot: {
        stats: [],
        endings: [],
        shortcuts: [],
        suggestedReplies: [],
        pinnedStartingSetupId: "physical-setup-1",
        sceneHeaderEnabled: true,
        initialScene: { place: null, time: "해 질 녘" },
      },
    });

    expect(state.contentSnapshot?.sceneHeaderEnabled).toBe(true);
    expect(state.contentSnapshot?.initialScene).toEqual({ place: undefined, time: "해 질 녘" });
    expect(state.messages[0]?.scene).toBeUndefined();
    expect(state.messages[1]?.scene).toEqual({ place: "갱도", time: undefined });
  });

  it("does not carry the judgment fields into the screen state even when an older server still sends them", () => {
    // 지금 서버 스키마에는 없는 칸이라 객체 리터럴로 바로 넣으면 타입 검사가 막는다 — 변수로 꺼내 옛 서버 응답 모양을 만든다.
    const olderServerStat = {
      id: "stat-1",
      name: "호감도",
      icon: "Heart",
      color: "#ff4d6d",
      minValue: 0,
      maxValue: 100,
      initialValue: 50,
      unit: null,
      description: "판정용 설명",
      playerDescription: null,
    };
    const olderServerEnding = {
      id: "ending-1",
      name: "해피엔딩",
      turnCountGate: 10,
      judgmentPrompt: "충분히 가까워졌는가?",
      epilogue: "그 후로 오래오래...",
      hint: "힌트",
      statRules: [{ kind: "rule" as const, id: "rule-1", statId: "stat-1", operator: "gte" as const, threshold: 80, nextOp: null }],
    };
    const response: components["schemas"]["ChatRoomResponse"] = {
      ...storyRoomBase,
      contentSnapshot: {
        stats: [olderServerStat],
        endings: [olderServerEnding],
        shortcuts: [],
        suggestedReplies: [],
        pinnedStartingSetupId: "physical-setup-1",
      },
    };

    const snapshot = toChatRoomState(response).contentSnapshot;

    expect(snapshot?.stats[0]).not.toHaveProperty("description");
    expect(snapshot?.endings).toEqual([{ id: "ending-1", name: "해피엔딩", turnGate: 10 }]);
  });
});
