import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage, ChatRoomState } from "../api/chat-room";
import { truncateAndEdit } from "./truncateAndEdit";

const ROOM_ID = "room-1";

function buildState(messages: ChatMessage[]): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "character-1",
    contentType: "character",
    name: "대화 1",
    messages,
    stats: {},
    endingStatus: { reached: false, endingId: null, reachedAtTurn: null, epilogue: null },
    turnCount: messages.length,
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
  };
}

describe("truncateAndEdit", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
  });

  it("updates the edited message content and drops every message after it", () => {
    const messages: ChatMessage[] = [
      { id: "m1", role: "user", content: "안녕", createdAt: "2026-07-08T00:00:00Z" },
      { id: "m2", role: "assistant", content: "반가워", createdAt: "2026-07-08T00:01:00Z" },
      { id: "m3", role: "user", content: "잘 지내?", createdAt: "2026-07-08T00:02:00Z" },
      { id: "m4", role: "assistant", content: "응 잘 지내", createdAt: "2026-07-08T00:03:00Z" },
    ];
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState(messages));

    truncateAndEdit(queryClient, ROOM_ID, "m1", "안녕하세요");

    const next = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID));
    expect(next?.messages).toEqual([{ ...messages[0], content: "안녕하세요" }]);
  });

  it("is a no-op when the message id is not found", () => {
    const messages: ChatMessage[] = [{ id: "m1", role: "user", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }];
    const initialState = buildState(messages);
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), initialState);

    truncateAndEdit(queryClient, ROOM_ID, "missing", "안녕하세요");

    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBe(initialState);
  });

  it("is a no-op when there is no cached state yet for the room", () => {
    truncateAndEdit(queryClient, ROOM_ID, "m1", "안녕하세요");

    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBeUndefined();
  });
});
