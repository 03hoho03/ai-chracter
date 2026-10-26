import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

import { removeOptimisticUserMessage } from "./removeOptimisticUserMessage";

const ROOM_ID = "room-1";
const SERVER_MESSAGES: ChatMessage[] = [
  { id: "m1", role: "user", content: "안녕", createdAt: "2026-10-04T00:00:00Z" },
  { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-10-04T00:01:00Z" },
];

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
    turnCount: 1,
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

describe("removeOptimisticUserMessage", () => {
  let queryClient: QueryClient;
  const optimistic: ChatMessage = { id: "local-1", role: "user", content: "보내려던 말", createdAt: "2026-10-04T00:02:00Z" };

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([...SERVER_MESSAGES, optimistic]));
  });

  // 클로버가 모자라 거절된 글은 입력 초안이 맡는다 — 말풍선을 남기면 돌아와 다시 보낼 때 같은 글이 둘이 된다.
  it("그 id 의 낙관적 메시지만 빼고 서버 메시지는 남긴다", () => {
    removeOptimisticUserMessage(queryClient, ROOM_ID, "local-1");
    expect(cachedMessages(queryClient)).toEqual(SERVER_MESSAGES);
  });

  it("그 id 가 없으면(그사이 방을 다시 받았으면) 아무것도 바꾸지 않는다", () => {
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(SERVER_MESSAGES));
    removeOptimisticUserMessage(queryClient, ROOM_ID, "local-1");
    expect(cachedMessages(queryClient)).toEqual(SERVER_MESSAGES);
  });

  it("방 캐시가 없으면 만들지 않는다", () => {
    queryClient.removeQueries({ queryKey: chatRoomKeys.detail(ROOM_ID) });
    removeOptimisticUserMessage(queryClient, ROOM_ID, "local-1");
    expect(cachedMessages(queryClient)).toBeUndefined();
  });
});
