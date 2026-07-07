import { describe, expect, it } from "vitest";

import { buildSendPayload } from "./buildSendPayload";

describe("buildSendPayload", () => {
  it("maps text to content and defaults shortcutId to null", () => {
    expect(buildSendPayload({ roomId: "room-1", text: "안녕" })).toEqual({
      roomId: "room-1",
      content: "안녕",
      shortcutId: null,
    });
  });

  it("passes through shortcutId when given", () => {
    expect(buildSendPayload({ roomId: "room-1", text: "/인사", shortcutId: "shortcut-1" })).toEqual({
      roomId: "room-1",
      content: "/인사",
      shortcutId: "shortcut-1",
    });
  });
});
