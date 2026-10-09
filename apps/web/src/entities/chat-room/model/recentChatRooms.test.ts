import { describe, expect, it } from "vitest";

import { RECENT_CHAT_ROOM_LIMIT, takeRecentChatRooms } from "./recentChatRooms";

const rooms = (count: number) => Array.from({ length: count }, (_, index) => `room-${index}`);

describe("takeRecentChatRooms", () => {
  it("limit 을 무시한 서버가 11개 이상을 주면 앞 10개만 순서대로 남긴다", () => {
    expect(RECENT_CHAT_ROOM_LIMIT).toBe(10);
    expect(takeRecentChatRooms(rooms(11))).toEqual(rooms(10));
    expect(takeRecentChatRooms(rooms(14))).toEqual(rooms(10));
  });

  it("10개 이하는 그대로 둔다", () => {
    expect(takeRecentChatRooms(rooms(10))).toEqual(rooms(10));
    expect(takeRecentChatRooms(rooms(3))).toEqual(rooms(3));
    expect(takeRecentChatRooms([])).toEqual([]);
  });
});
