import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys } from "@/entities/chat-room";
import type { ChatMessage, ChatRoomState } from "@/entities/chat-room";

import { addOptimisticUserMessage } from "./addOptimisticUserMessage";

const ROOM_ID = "room-1";
const SERVER_MESSAGES: ChatMessage[] = [
  { id: "m1", role: "user", content: "안녕", createdAt: "2026-10-04T00:00:00Z" },
  { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-10-04T00:01:00Z" },
];
const OPTIMISTIC: ChatMessage = { id: "local-1", role: "user", content: "다음 말", createdAt: "2026-10-04T00:02:00Z" };

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

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("addOptimisticUserMessage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(SERVER_MESSAGES));
  });

  it("appends the message to the room", () => {
    addOptimisticUserMessage(queryClient, ROOM_ID, OPTIMISTIC);

    expect(cachedMessages(queryClient)).toEqual([...SERVER_MESSAGES, OPTIMISTIC]);
  });

  // 삭제·수정 뒤 방을 다시 받는 중에 보내면, 그 조회가 늦게 도착해 방금 둔 말풍선을 지운다.
  it("keeps the message when a refetch that was already in flight finishes or is cancelled", async () => {
    let resolveFetch: (state: ChatRoomState) => void = () => {};
    const inFlight = queryClient
      .fetchQuery({
        queryKey: chatRoomKeys.detail(ROOM_ID),
        queryFn: () => new Promise<ChatRoomState>((resolve) => (resolveFetch = resolve)),
      })
      .catch(() => undefined);

    addOptimisticUserMessage(queryClient, ROOM_ID, OPTIMISTIC);
    resolveFetch(buildState(SERVER_MESSAGES));
    await inFlight;
    await flush();

    expect(cachedMessages(queryClient)).toEqual([...SERVER_MESSAGES, OPTIMISTIC]);
  });
});
