import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { chatRoomKeys } from "./keys";
import { fetchChatRoom } from "./useChatRoomQuery";
import { postPinLatestVersion } from "./usePinLatestVersionMutation";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { get, post } }));

const ROOM_ID = "room-1";
const RESPONSE = {
  data: {
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
    createdAt: "2026-10-05T00:00:00Z",
    updatedAt: "2026-10-05T00:00:00Z",
  },
};

function cacheWith(queryClient: QueryClient, count: number) {
  queryClient.setQueryData(chatRoomKeys.detail(ROOM_ID), {
    messages: Array.from({ length: count }, (_, index) => ({ id: `m${index}` })),
  });
}

// 방 상세를 다시 받거나 버전을 고정하면 응답이 캐시를 통째로 바꾼다 — 위로 불러 둔 깊이만큼 받아야 그 메시지가 남는다.
describe("chat room requests that replace the cached room", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient();
    get.mockReset().mockResolvedValue(RESPONSE);
    post.mockReset().mockResolvedValue(RESPONSE);
  });

  it("fetches one page on first entry", async () => {
    await fetchChatRoom(queryClient, ROOM_ID);

    expect(get).toHaveBeenCalledWith(`/chat-rooms/${ROOM_ID}`, { params: { messageLimit: 50 } });
  });

  it("refetches as deep as the cache already goes", async () => {
    cacheWith(queryClient, 130);

    await fetchChatRoom(queryClient, ROOM_ID);

    expect(get).toHaveBeenCalledWith(`/chat-rooms/${ROOM_ID}`, { params: { messageLimit: 130 } });
  });

  it("pins the latest version without cutting what the user loaded", async () => {
    cacheWith(queryClient, 130);

    await postPinLatestVersion(queryClient, ROOM_ID);

    expect(post).toHaveBeenCalledWith(`/chat-rooms/${ROOM_ID}/pin-latest-version`, undefined, {
      params: { messageLimit: 130 },
    });
  });
});
