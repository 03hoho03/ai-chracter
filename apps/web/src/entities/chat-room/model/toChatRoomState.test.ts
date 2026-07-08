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
      endingStatus: { reached: false, endingId: null, reachedAtTurn: null },
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

    expect(state.endingStatus).toEqual({ reached: true, endingId: null, reachedAtTurn: null });
  });
});
