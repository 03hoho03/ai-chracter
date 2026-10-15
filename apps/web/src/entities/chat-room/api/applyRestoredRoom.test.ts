import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api/client", () => ({ apiClient: {} }));

import { chatRoomKeys } from "./keys";
import { applyRestoredRoom } from "./useRestorePreviousResponseMutation";
import type { ChatRoomState } from "../model/chatRoomState";

const ROOM_ID = "room-1";

function buildState(overrides: Partial<ChatRoomState>): ChatRoomState {
  return {
    id: ROOM_ID,
    contentId: "story-1",
    contentType: "story",
    name: "대화 1",
    startingSetupId: "setup-1",
    contentVersion: 1,
    contentSnapshot: undefined,
    messages: [],
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
    ...overrides,
  };
}

const user = { id: "u1", role: "user" as const, content: "안녕", createdAt: "2026-10-15T00:00:00Z" };
const regenerated = { id: "a1-regen", role: "assistant" as const, content: "새 답", createdAt: "2026-10-15T00:02:00Z" };
const original = { id: "a1", role: "assistant" as const, content: "옛 답", createdAt: "2026-10-15T00:01:00Z" };

const beforeRestore = buildState({ messages: [user, regenerated], stats: { hp: 70 }, previousResponseFor: "a1-regen" });
const restored = buildState({ messages: [user, original], stats: { hp: 40 }, previousResponseFor: "a1" });

describe("applyRestoredRoom", () => {
  it("되돌린 방 상태로 메시지·스탯·되돌릴 답 표시를 한 번에 바꾼다", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), beforeRestore);

    await applyRestoredRoom(queryClient, ROOM_ID, restored);

    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toEqual(restored);
  });

  it("되돌리기 전에 떠난 방 조회가 늦게 도착해도 되돌린 답을 옛 답으로 덮지 않는다", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), beforeRestore);
    let resolveStaleFetch: (room: ChatRoomState) => void = () => {};
    const staleFetch = queryClient
      .fetchQuery({
        queryKey: chatRoomKeys.detail(ROOM_ID),
        queryFn: () => new Promise<ChatRoomState>((resolve) => (resolveStaleFetch = resolve)),
        staleTime: 0,
      })
      .catch(() => undefined);

    await applyRestoredRoom(queryClient, ROOM_ID, restored);
    resolveStaleFetch(beforeRestore);
    await staleFetch;

    expect(queryClient.getQueryData(chatRoomKeys.detail(ROOM_ID))).toEqual(restored);
  });

  it("기억과 내 방 목록을 낡은 값으로 표시한다", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await applyRestoredRoom(queryClient, ROOM_ID, restored);

    expect(invalidate).toHaveBeenCalledWith({ queryKey: chatRoomKeys.memory(ROOM_ID) });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: chatRoomKeys.myLists() });
  });
});
