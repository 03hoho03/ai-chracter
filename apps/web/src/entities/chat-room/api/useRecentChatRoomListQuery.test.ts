import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchRecentChatRooms } from "./useRecentChatRoomListQuery";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { get } }));

const rooms = (count: number) => Array.from({ length: count }, (_, index) => ({ id: `room-${index}` }));

// 서버 배포 순서와 상관없이 최근 대화 캐시에는 10개만 들어가야 한다 — `limit` 을 모르는 옛 API 는 전체를 준다.
describe("fetchRecentChatRooms", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("asks the server for 10 rooms", async () => {
    get.mockResolvedValue({ data: rooms(3) });

    await fetchRecentChatRooms();

    expect(get).toHaveBeenCalledWith("/me/chat-rooms", { params: { limit: 10 } });
  });

  it("keeps the first 10 in order when the server ignores the limit and returns 14", async () => {
    get.mockResolvedValue({ data: rooms(14) });

    expect(await fetchRecentChatRooms()).toEqual(rooms(10));
  });
});
