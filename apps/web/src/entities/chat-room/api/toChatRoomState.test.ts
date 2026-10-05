import { describe, expect, it } from "vitest";

import { toChatRoomState } from "./toChatRoomState";

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
      defaultUserName: "",
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
    });
  });

  // 화면이 작가 글의 `{{user}}`·`{{char}}` 를 방이 고정한 버전의 이름으로 바꾸려면 세 이름이 방 상태에 있어야 한다.
  // 프로필 없음(서버 null)은 undefined 로 접는다 — 이름 고르기가 다음 순서(작품 기본 이름)로 넘어간다.
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
      toChatRoomState({ ...base, personaName: "지훈", defaultUserName: "조감독", contentName: "유나" }),
    ).toMatchObject({ personaName: "지훈", defaultUserName: "조감독", contentName: "유나" });
    expect(toChatRoomState({ ...base, personaName: null })).toMatchObject({
      personaName: undefined,
      defaultUserName: "",
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

  it("carries the endingReached flag through into endingStatus.reached", () => {
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

  it("maps story chat contentSnapshot/stats/startingSetupId, translating raw operators to comparison symbols", () => {
    const state = toChatRoomState({
      id: "room-2",
      contentId: "story-1",
      contentType: "story",
      name: "대화 1",
      startingSetupId: "setup-1",
      turnCount: 5,
      endingReached: false,
      stats: { "stat-1": 42 },
      messages: [],
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
            description: "캐릭터와의 호감도",
          },
        ],
        endings: [
          {
            id: "ending-1",
            name: "해피엔딩",
            turnCountGate: 10,
            judgmentPrompt: "충분히 가까워졌는가?",
            epilogue: "그 후로 오래오래...",
            hint: null,
            statRules: [
              { kind: "rule", id: "rule-1", statId: "stat-1", operator: "gte", threshold: 80, nextOp: null },
              {
                kind: "group",
                id: "group-1",
                nextOp: "or",
                rules: [{ kind: "rule", id: "rule-2", statId: "stat-1", operator: "lt", threshold: 10, nextOp: null }],
              },
            ],
          },
        ],
        shortcuts: [{ id: "shortcut-1", name: "인사", description: "인사하기", prompt: "안녕이라고 인사해줘" }],
        suggestedReplies: ["계속 이야기해줘"],
        pinnedStartingSetupId: "physical-setup-1",
      },
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
      contentRestricted: false,
      hasMoreMessagesBefore: false,
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
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
          description: "캐릭터와의 호감도",
        },
      ],
      endings: [
        {
          id: "ending-1",
          name: "해피엔딩",
          turnGate: 10,
          judgePrompt: "충분히 가까워졌는가?",
          epilogue: "그 후로 오래오래...",
          endingHint: undefined,
          statRules: [
            { kind: "rule", id: "rule-1", statId: "stat-1", operator: ">=", value: 80, nextOp: null },
            {
              kind: "group",
              id: "group-1",
              nextOp: "or",
              rules: [{ kind: "rule", id: "rule-2", statId: "stat-1", operator: "<", value: 10, nextOp: null }],
            },
          ],
        },
      ],
      shortcuts: [{ id: "shortcut-1", name: "인사", description: "인사하기", prompt: "안녕이라고 인사해줘" }],
      suggestedReplies: ["계속 이야기해줘"],
      pinnedStartingSetupId: "physical-setup-1",
    });
  });
});
