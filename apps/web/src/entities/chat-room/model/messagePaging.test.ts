import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage } from "../api/chatStream";
import { applyStreamEvent } from "./applyStreamEvent";
import type { ChatRoomState } from "./chatRoomState";
import { CHAT_ROOM_MESSAGE_PAGE_SIZE, chatRoomMessageLimit, prependOlderMessages } from "./messagePaging";

const ROOM_ID = "room-1";

function message(id: string, role: ChatMessage["role"] = "assistant"): ChatMessage {
  return { id, role, content: id, createdAt: "2026-10-05T00:00:00Z" };
}

function messages(from: number, to: number): ChatMessage[] {
  return Array.from({ length: to - from }, (_, offset) => message(`m${from + offset}`));
}

function buildState(roomMessages: ChatMessage[], hasMoreMessagesBefore = true): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "story-1",
    contentType: "story",
    name: "대화 1",
    messages: roomMessages,
    openingMediaTagImages: {},
    stats: {},
    endingStatus: { reached: false, endingId: undefined, reachedAtTurn: undefined, epilogue: undefined },
    turnCount: 60,
    defaultUserName: "",
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    contentRestricted: false,
    effectiveChatModel: "gemini",
    turnCost: 10,
    hasMoreMessagesBefore,
  };
}

describe("chatRoomMessageLimit", () => {
  it("asks for one page when nothing is cached yet", () => {
    expect(chatRoomMessageLimit(undefined)).toBe(CHAT_ROOM_MESSAGE_PAGE_SIZE);
  });

  it("asks for one page when the cache holds less than that", () => {
    expect(chatRoomMessageLimit(buildState(messages(0, 3)))).toBe(CHAT_ROOM_MESSAGE_PAGE_SIZE);
  });

  it("asks for every cached message once the user has loaded deeper than one page", () => {
    expect(chatRoomMessageLimit(buildState(messages(0, 120)))).toBe(120);
  });
});

describe("prependOlderMessages", () => {
  it("puts the older page in front and takes the page's has-more flag", () => {
    const prev = buildState(messages(50, 100));

    const next = prependOlderMessages(prev, { messages: messages(0, 50), hasMoreBefore: false }, "m50");

    expect(next?.messages.map((m) => m.id)).toEqual(messages(0, 100).map((m) => m.id));
    expect(next?.hasMoreMessagesBefore).toBe(false);
  });

  it("does not add a message the cache already holds", () => {
    const prev = buildState(messages(50, 100));

    const next = prependOlderMessages(prev, { messages: messages(10, 51), hasMoreBefore: true }, "m50");

    expect(next?.messages.map((m) => m.id)).toEqual(messages(10, 100).map((m) => m.id));
  });

  it("drops the page when the cache no longer starts at the cursor it was asked for", () => {
    // 요청한 사이 재조회가 캐시를 바꿨다 — 페이지와 지금 첫 메시지 사이가 이어진다는 보장이 없다.
    const prev = buildState(messages(53, 103));

    const next = prependOlderMessages(prev, { messages: messages(0, 50), hasMoreBefore: false }, "m50");

    expect(next).toBe(prev);
  });

  it("leaves an empty cache empty", () => {
    expect(prependOlderMessages(undefined, { messages: messages(0, 50), hasMoreBefore: false }, "m50")).toBeUndefined();
  });

  it("keeps the tail a stream just finished, in either order", () => {
    const queryClient = new QueryClient();
    const finalMessage = message("reply");
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([...messages(50, 99), message("u", "user")]));

    applyStreamEvent(queryClient, ROOM_ID, { type: "done", finalMessage });
    queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID), (prev) =>
      prependOlderMessages(prev, { messages: messages(0, 50), hasMoreBefore: false }, "m50"),
    );

    const ids = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages.map((m) => m.id);
    expect(ids?.slice(0, 50)).toEqual(messages(0, 50).map((m) => m.id));
    expect(ids?.slice(-2)).toEqual(["u", "reply"]);
    expect(ids).toHaveLength(101);
  });

  it("lets a stream append after older messages were put in front", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), buildState([...messages(50, 99), message("u", "user")]));

    queryClient.setQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID), (prev) =>
      prependOlderMessages(prev, { messages: messages(0, 50), hasMoreBefore: false }, "m50"),
    );
    applyStreamEvent(queryClient, ROOM_ID, { type: "done", finalMessage: message("reply") });

    const state = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID));
    expect(state?.messages[0]?.id).toBe("m0");
    expect(state?.messages.at(-1)?.id).toBe("reply");
    expect(state?.hasMoreMessagesBefore).toBe(false);
  });
});
