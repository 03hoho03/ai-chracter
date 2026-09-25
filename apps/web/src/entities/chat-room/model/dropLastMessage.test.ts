import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage } from "../api/chatStream";
import { dropLastMessage, restoreMessage } from "./dropLastMessage";
import type { ChatRoomState } from "./chatRoomState";

const ROOM_ID = "room-1";

function buildState(messages: ChatMessage[]): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "character-1",
    contentType: "character",
    name: "대화 1",
    messages,
    stats: {},
    endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: messages.length,
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
  };
}

describe("dropLastMessage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
  });

  it("removes the trailing assistant message and returns it", () => {
    const userMessage: ChatMessage = { id: "m1", role: "user", content: "안녕", createdAt: "2026-07-08T00:00:00Z" };
    const assistantMessage: ChatMessage = {
      id: "m2",
      role: "assistant",
      content: "반가워",
      createdAt: "2026-07-08T00:01:00Z",
    };
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([userMessage, assistantMessage]));

    const dropped = dropLastMessage(queryClient, ROOM_ID);

    expect(dropped).toEqual(assistantMessage);
    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages).toEqual([
      userMessage,
    ]);
  });

  it("is a no-op returning undefined when there is no cached state or messages is empty", () => {
    const dropped1 = dropLastMessage(queryClient, ROOM_ID);
    expect(dropped1).toBeUndefined();
    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBeUndefined();

    const emptyState = buildState([]);
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), emptyState);

    const dropped2 = dropLastMessage(queryClient, ROOM_ID);
    expect(dropped2).toBeUndefined();
    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBe(emptyState);
  });

  // 마지막이 user면 지우지 않는다. retry()가 같은 payload로
  // 다시 들어올 때 캐시가 그 사이 재조회로 바뀌어 있을 수 있다.
  it("is a no-op returning undefined when the last message is a user message", () => {
    const messages: ChatMessage[] = [
      { id: "m1", role: "assistant", content: "반가워", createdAt: "2026-07-08T00:00:00Z" },
      { id: "m2", role: "user", content: "안녕", createdAt: "2026-07-08T00:01:00Z" },
    ];
    const initialState = buildState(messages);
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), initialState);

    const dropped = dropLastMessage(queryClient, ROOM_ID);

    expect(dropped).toBeUndefined();
    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBe(initialState);
  });

  it("restoreMessage round-trips the array back to its original order", () => {
    const userMessage: ChatMessage = { id: "m1", role: "user", content: "안녕", createdAt: "2026-07-08T00:00:00Z" };
    const assistantMessage: ChatMessage = {
      id: "m2",
      role: "assistant",
      content: "반가워",
      createdAt: "2026-07-08T00:01:00Z",
    };
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([userMessage, assistantMessage]));
    const dropped = dropLastMessage(queryClient, ROOM_ID);
    if (!dropped) throw new Error("dropped must be defined for this test");

    restoreMessage(queryClient, ROOM_ID, dropped);

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages).toEqual([
      userMessage,
      assistantMessage,
    ]);
  });

  // 같은 id가 이미 있으면 아무것도 하지 않는다. 재조회가 먼저
  // 되살린 뒤 finally가 한 번 더 붙이면 같은 메시지가 두 벌 남는다.
  it("is a no-op when a message with the same id already exists", () => {
    const userMessage: ChatMessage = { id: "m1", role: "user", content: "안녕", createdAt: "2026-07-08T00:00:00Z" };
    const assistantMessage: ChatMessage = {
      id: "m2",
      role: "assistant",
      content: "반가워",
      createdAt: "2026-07-08T00:01:00Z",
    };
    const stateWithBothMessages = buildState([userMessage, assistantMessage]);
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), stateWithBothMessages);

    restoreMessage(queryClient, ROOM_ID, assistantMessage);

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages).toEqual([
      userMessage,
      assistantMessage,
    ]);
  });
});
