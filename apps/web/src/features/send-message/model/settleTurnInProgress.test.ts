import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys, truncateAndEdit } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

import { settleTurnInProgress } from "./settleTurnInProgress";

const ROOM_ID = "room-1";
const MESSAGES: ChatMessage[] = [
  { id: "m1", role: "user", content: "안녕", createdAt: "2026-10-04T00:00:00Z" },
  { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-10-04T00:01:00Z" },
  { id: "m3", role: "user", content: "잘 지내?", createdAt: "2026-10-04T00:02:00Z" },
  { id: "m4", role: "assistant", content: "응 잘 지내", createdAt: "2026-10-04T00:03:00Z" },
];
const TURN_IN_PROGRESS = { status: 409, detail: { code: "CHAT_TURN_IN_PROGRESS" }, message: "x" };

function buildState(messages: ChatMessage[]): ChatRoomState {
  return {
    id: ROOM_ID,
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
    effectiveChatModel: "gemini",
    turnCost: 10,
    hasMoreMessagesBefore: false,
  };
}

function cachedMessages(queryClient: QueryClient): ChatMessage[] | undefined {
  return queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages;
}

describe("settleTurnInProgress", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(MESSAGES));
  });

  it("수정이 앞 턴 때문에 거절되면 잘라 둔 목록을 수정 전으로 되돌린다 — 서버는 아무것도 자르지 않았다", () => {
    const beforeEdit = truncateAndEdit(queryClient, ROOM_ID, "m1", "안녕하세요");
    expect(cachedMessages(queryClient)).toHaveLength(1);

    expect(settleTurnInProgress(queryClient, ROOM_ID, TURN_IN_PROGRESS, beforeEdit)).toBe(true);

    expect(cachedMessages(queryClient)).toEqual(MESSAGES);
  });

  it("보내기·재생성처럼 되돌릴 목록이 없으면 판정만 하고 캐시는 그대로 둔다", () => {
    expect(settleTurnInProgress(queryClient, ROOM_ID, TURN_IN_PROGRESS, undefined)).toBe(true);

    expect(cachedMessages(queryClient)).toEqual(MESSAGES);
  });

  it("다른 오류는 이 갈래가 아니다 — 잘린 목록도 기존처럼 그대로 남는다", () => {
    const beforeEdit = truncateAndEdit(queryClient, ROOM_ID, "m1", "안녕하세요");
    const others = [
      { status: 429, detail: { code: "CHAT_BURST_LIMIT" }, message: "x" },
      { status: 409, detail: { code: "MEMORY_VERSION_CONFLICT" }, message: "x" },
      { status: 500, detail: undefined, message: "x" },
    ];

    for (const error of others) {
      expect(settleTurnInProgress(queryClient, ROOM_ID, error, beforeEdit)).toBe(false);
    }
    expect(cachedMessages(queryClient)).toEqual([{ ...MESSAGES[0], content: "안녕하세요" }]);
  });
});
