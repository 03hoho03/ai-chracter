import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { chatRoomKeys } from "./keys";
import { refreshChatRoomTurnPrice } from "./refreshChatRoomTurnPrice";
import type { ChatRoomState } from "../model/chatRoomState";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { get } }));

const ROOM_ID = "room-1";
// 서버는 상위 모델이 꺼져 기본 모델로 돌렸다. 메시지 목록은 비어 있다(거절된 사용자 메시지는 저장되지 않았다).
const SERVER_ROOM = {
  id: ROOM_ID,
  contentId: "c",
  contentType: "character",
  name: "대화 1",
  turnCount: 0,
  endingReached: false,
  messages: [],
  hasMoreMessagesBefore: false,
  latestVersionAvailable: false,
  versionAutoUpgraded: false,
  contentRestricted: false,
  effectiveChatModel: "gemini",
  effectiveChatModelName: "Gemini",
  turnCost: 10,
  createdAt: "2026-10-05T00:00:00Z",
  updatedAt: "2026-10-05T00:00:00Z",
};
const OPTIMISTIC_MESSAGE = { id: "local", role: "user", content: "안녕", createdAt: "2026-10-05T00:00:00Z" };

describe("refreshChatRoomTurnPrice", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    // 캐시는 상위 모델 방이던 때의 값이다.
    queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), {
      messages: [OPTIMISTIC_MESSAGE],
      effectiveChatModel: "opus",
      effectiveChatModelName: "Claude Opus 5.5",
      turnCost: 65,
    });
    get.mockReset().mockResolvedValue({ data: SERVER_ROOM });
  });

  it("returns the server's price, not the cached one", async () => {
    await expect(refreshChatRoomTurnPrice(queryClient, ROOM_ID)).resolves.toBe(10);
  });

  it("writes the fresh model, its name and price into the cache so the shortage notice and the model chip follow", async () => {
    await refreshChatRoomTurnPrice(queryClient, ROOM_ID);

    const cached = queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID));
    expect(cached?.effectiveChatModel).toBe("gemini");
    expect(cached?.effectiveChatModelName).toBe("Gemini");
    expect(cached?.turnCost).toBe(10);
  });

  it("keeps the unsent user message that the server never stored", async () => {
    await refreshChatRoomTurnPrice(queryClient, ROOM_ID);

    expect(queryClient.getQueryData<ChatRoomState>(chatRoomKeys.detail(ROOM_ID))?.messages).toEqual([
      OPTIMISTIC_MESSAGE,
    ]);
  });

  it("falls back to the cached price when the refetch fails", async () => {
    get.mockRejectedValue(new Error("network"));

    await expect(refreshChatRoomTurnPrice(queryClient, ROOM_ID)).resolves.toBe(65);
  });
});
