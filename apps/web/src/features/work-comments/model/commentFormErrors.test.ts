import { describe, expect, it } from "vitest";

import { commentFormErrors } from "./commentFormErrors";

describe("comment server validation boundaries", () => {
  it.each([
    ["COMMENT_MENTION_INVALID", "mentions"], ["COMMENT_STICKER_INVALID", "stickerId"],
    ["COMMENT_EMPTY", "body"], ["COMMENT_TEXT_TOO_LONG", "body"],
  ])("maps %s to the corresponding RHF field", (code, field) => {
    expect(commentFormErrors({ status: 422, message: "server", detail: { code } })).toEqual([
      expect.objectContaining({ field, message: expect.any(String) }),
    ]);
  });
  it("maps normalized snake/camel field names without exposing raw server messages", () => {
    const errors = commentFormErrors({ status: 422, message: "server", fields: {
      body: "English server validation", stickerId: "English", mention_user_ids: "English", is_spoiler: "English",
    } });
    expect(errors.map((error) => error.field)).toEqual(["body", "stickerId", "mentions", "isSpoiler"]);
    expect(errors.every((error) => !error.message.includes("English"))).toBe(true);
  });
  it("keeps rate and network failures at the root and preserves the retry message", () => {
    expect(commentFormErrors({ status: 429, message: "server", detail: { retryAfterSeconds: 25 } })).toEqual([
      { field: "root", message: "25초 후 다시 시도할 수 있어요. 입력은 유지돼요." },
    ]);
    expect(commentFormErrors(new Error("network"))[0]?.field).toBe("root");
    expect(commentFormErrors({ status: 422, message: "server", fields: { unknown: "English" } })[0]?.field).toBe("root");
  });
});
