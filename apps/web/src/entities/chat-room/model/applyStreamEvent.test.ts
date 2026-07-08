import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { chatRoomKeys } from "../api/keys";
import type { ChatMessage, ChatRoomState } from "../api/types";
import { applyStreamEvent } from "./applyStreamEvent";

const ROOM_ID = "room-1";

function buildState(overrides: Partial<ChatRoomState> = {}): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "story-1",
    contentType: "story",
    name: "대화 1",
    startingSetupId: "setup-1",
    contentVersion: 1,
    contentSnapshot: { stats: [], endings: [], shortcuts: [], suggestedReplies: [] },
    messages: [{ id: "m1", role: "assistant", content: "안녕", createdAt: "2026-07-08T00:00:00Z" }],
    stats: { hp: 50 },
    endingStatus: { reached: false, endingId: null, reachedAtTurn: null },
    turnCount: 3,
    latestVersionAvailable: false,
    versionAutoUpgraded: false,
    ...overrides,
  };
}

describe("applyStreamEvent", () => {
  let queryClient: QueryClient;
  let initialState: ChatRoomState;

  beforeEach(() => {
    queryClient = new QueryClient();
    initialState = buildState();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), initialState);
  });

  it("does not touch the cache for token/policyWarning/error", () => {
    applyStreamEvent(queryClient, ROOM_ID, { type: "token", delta: "hi" });
    applyStreamEvent(queryClient, ROOM_ID, { type: "policyWarning", message: "주의" });
    applyStreamEvent(queryClient, ROOM_ID, { type: "error", message: "네트워크 오류" });

    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBe(initialState);
  });

  it("statChange overwrites with the event's absolute newValue", () => {
    applyStreamEvent(queryClient, ROOM_ID, { type: "statChange", statId: "hp", newValue: 12 });

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.stats).toEqual({ hp: 12 });
  });

  it("statChange adds a new statId without disturbing existing ones", () => {
    applyStreamEvent(queryClient, ROOM_ID, { type: "statChange", statId: "mp", newValue: 7 });

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.stats).toEqual({
      hp: 50,
      mp: 7,
    });
  });

  it("endingReached sets endingStatus using the current turnCount", () => {
    applyStreamEvent(queryClient, ROOM_ID, { type: "endingReached", endingId: "ending-1", epilogue: "끝" });

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.endingStatus).toEqual({
      reached: true,
      endingId: "ending-1",
      reachedAtTurn: 3,
    });
  });

  it("done appends the final message and increments turnCount by default (mode: append)", () => {
    const finalMessage: ChatMessage = { id: "m2", role: "assistant", content: "다음 대사", createdAt: "2026-07-08T00:01:00Z" };

    applyStreamEvent(queryClient, ROOM_ID, { type: "done", finalMessage });

    const next = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID));
    expect(next?.messages).toEqual([...initialState.messages, finalMessage]);
    expect(next?.turnCount).toBe(4);
  });

  it("done replaces the last message when mode is replaceLast, and still increments turnCount", () => {
    const finalMessage: ChatMessage = { id: "m1-regen", role: "assistant", content: "다시 생성됨", createdAt: "2026-07-08T00:02:00Z" };

    applyStreamEvent(queryClient, ROOM_ID, { type: "done", finalMessage }, { mode: "replaceLast" });

    const next = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID));
    expect(next?.messages).toEqual([finalMessage]);
    expect(next?.turnCount).toBe(4);
  });

  it("done calls onDone with the final message and the pre-update state", () => {
    const finalMessage: ChatMessage = { id: "m2", role: "assistant", content: "다음 대사", createdAt: "2026-07-08T00:01:00Z" };
    const onDone = vi.fn();

    applyStreamEvent(queryClient, ROOM_ID, { type: "done", finalMessage }, { onDone });

    expect(onDone).toHaveBeenCalledWith(finalMessage, initialState);
  });

  it("is a no-op when there is no cached state yet for the room", () => {
    const emptyClient = new QueryClient();

    applyStreamEvent(emptyClient, ROOM_ID, { type: "statChange", statId: "hp", newValue: 1 });
    applyStreamEvent(emptyClient, ROOM_ID, { type: "endingReached", endingId: "e1", epilogue: null });
    applyStreamEvent(emptyClient, ROOM_ID, {
      type: "done",
      finalMessage: { id: "m1", role: "assistant", content: "x", createdAt: "2026-07-08T00:00:00Z" },
    });

    expect(emptyClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toBeUndefined();
  });
});
