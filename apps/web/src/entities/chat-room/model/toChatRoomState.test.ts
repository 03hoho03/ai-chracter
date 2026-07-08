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
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state).toEqual({
      id: "room-1",
      contentId: "content-1",
      contentType: "character",
      name: "대화 1",
      messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
      stats: {},
      endingStatus: { reached: false, endingId: null, reachedAtTurn: null, epilogue: null },
      turnCount: 3,
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
    });
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
      createdAt: "2026-07-08T00:00:00Z",
      updatedAt: "2026-07-08T00:00:00Z",
    });

    expect(state.endingStatus).toEqual({ reached: true, endingId: null, reachedAtTurn: null, epilogue: null });
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
      },
      latestVersionAvailable: true,
      versionAutoUpgraded: false,
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
    });
  });
});
