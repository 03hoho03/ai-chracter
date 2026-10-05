import { describe, expect, it } from "vitest";

import { isStillInRoom } from "./roomNovelNavigation";

describe("isStillInRoom", () => {
  it("응답이 왔을 때 아직 그 방 화면이면 참이다", () => {
    expect(isStillInRoom("/chat/room-1", "room-1")).toBe(true);
  });

  it("그 사이 다른 방이나 다른 화면으로 옮겼으면 거짓이다", () => {
    expect(isStillInRoom("/chat/room-2", "room-1")).toBe(false);
    expect(isStillInRoom("/", "room-1")).toBe(false);
    expect(isStillInRoom("/novels", "room-1")).toBe(false);
  });
});
