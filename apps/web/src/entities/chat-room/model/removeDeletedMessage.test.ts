import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../api/chatStream";
import type { ChatRoomState } from "./chatRoomState";
import { removeDeletedMessage } from "./removeDeletedMessage";

function buildState(messages: ChatMessage[], previousResponseFor?: string): ChatRoomState {
  return {
    id: "room-1",
    contentId: "character-1",
    contentType: "character",
    name: "대화 1",
    messages,
    openingMediaTagImages: {},
    stats: {},
    endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: 2,
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
    novelCreationBlocked: false,
    previousResponseFor,
    effectiveChatModel: "gemini",
    turnCost: 10,
    hasMoreMessagesBefore: false,
  };
}

const firstUser: ChatMessage = { id: "u1", role: "user", content: "안녕", createdAt: "2026-10-15T00:00:00Z" };
const firstReply: ChatMessage = { id: "a1", role: "assistant", content: "반가워", createdAt: "2026-10-15T00:01:00Z" };
const regenerated: ChatMessage = { id: "a2-regen", role: "assistant", content: "새 답", createdAt: "2026-10-15T00:03:00Z" };

describe("removeDeletedMessage", () => {
  it("지운 메시지만 빼고 나머지 순서는 그대로 둔다", () => {
    const room = buildState([firstUser, firstReply, regenerated]);

    expect(removeDeletedMessage(room, "a1").messages).toEqual([firstUser, regenerated]);
  });

  it("앞쪽 메시지를 지워 재생성한 응답이 여전히 마지막이어도 되돌릴 답 표시를 비운다", () => {
    const room = buildState([firstUser, firstReply, regenerated], "a2-regen");

    const next = removeDeletedMessage(room, "u1");

    expect(next.messages.at(-1)?.id).toBe("a2-regen");
    expect(next.previousResponseFor).toBeUndefined();
  });
});
