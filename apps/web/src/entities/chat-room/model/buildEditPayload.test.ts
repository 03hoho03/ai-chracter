import { describe, expect, it } from "vitest";

import { buildEditPayload } from "./buildEditPayload";

describe("buildEditPayload", () => {
  it("maps text to content for the given room/message", () => {
    expect(buildEditPayload({ roomId: "room-1", messageId: "msg-1", text: "수정된 내용" })).toEqual({
      kind: "edit",
      roomId: "room-1",
      messageId: "msg-1",
      content: "수정된 내용",
    });
  });
});
