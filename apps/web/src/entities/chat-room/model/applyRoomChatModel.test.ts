import { describe, expect, it } from "vitest";

import { applyRoomChatModel } from "./applyRoomChatModel";
import type { ChatRoomState } from "./chatRoomState";

const MESSAGE = { id: "m1", role: "user" as const, content: "안녕", createdAt: "2026-10-10T00:00:00Z" };

function room(overrides: Partial<ChatRoomState> = {}): ChatRoomState {
  return {
    id: "room-1",
    contentId: "c",
    contentType: "character",
    name: "대화 1",
    messages: [MESSAGE],
    hasMoreMessagesBefore: false,
    openingMediaTagImages: {},
    stats: {},
    endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: 1,
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
    novelCreationBlocked: false,
    effectiveChatModel: "gemini",
    effectiveChatModelName: "Gemini",
    turnCost: 10,
    ...overrides,
  };
}

describe("applyRoomChatModel", () => {
  // 헤더 칩은 방 캐시의 이름을 그린다 — 이름을 빼고 모델만 고치면 칩이 옛 모델 이름으로 남는다.
  it("모델·이름·턴 가격 셋을 함께 고친다", () => {
    const next = applyRoomChatModel(room(), {
      effectiveChatModel: "opus",
      effectiveChatModelName: "Claude Opus 5.5",
      turnCost: 120,
    });

    expect(next?.effectiveChatModel).toBe("opus");
    expect(next?.effectiveChatModelName).toBe("Claude Opus 5.5");
    expect(next?.turnCost).toBe(120);
  });

  // 모델 모달의 안내는 저장한 모델과 실제 모델을 견준다 — 저장한 모델을 빠뜨리면 이미 고친 방에 안내가 남는다.
  it("저장한 모델도 고치고, 기본 모델의 null 은 undefined 로 접는다", () => {
    const fallenBack = room({ chatModel: "opus", effectiveChatModel: "gemini" });

    expect(
      applyRoomChatModel(fallenBack, {
        chatModel: "opus",
        effectiveChatModel: "opus",
        effectiveChatModelName: "Claude Opus 5.5",
        turnCost: 120,
      })?.chatModel,
    ).toBe("opus");
    expect(
      applyRoomChatModel(fallenBack, {
        chatModel: null,
        effectiveChatModel: "gemini",
        effectiveChatModelName: "Gemini",
        turnCost: 10,
      })?.chatModel,
    ).toBeUndefined();
  });

  it("메시지 등 나머지 칸은 그대로 둔다", () => {
    const next = applyRoomChatModel(room(), { effectiveChatModel: "opus", effectiveChatModelName: "Claude Opus 5.5", turnCost: 120 });

    expect(next?.messages).toEqual([MESSAGE]);
    expect(next?.name).toBe("대화 1");
  });

  it("캐시가 비어 있으면 그대로 비워 둔다", () => {
    expect(
      applyRoomChatModel(undefined, { effectiveChatModel: "opus", effectiveChatModelName: "Claude Opus 5.5", turnCost: 120 }),
    ).toBeUndefined();
  });
});
