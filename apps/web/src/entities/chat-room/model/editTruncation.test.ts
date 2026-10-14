import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../api/chatStream";
import { countMessagesAfter, shouldConfirmEditTruncation } from "./editTruncation";

function message(id: string, role: ChatMessage["role"]): ChatMessage {
  return { id, role, content: id, createdAt: "2026-10-15T00:00:00Z" };
}

const MESSAGES: ChatMessage[] = [
  message("a1", "assistant"),
  message("u1", "user"),
  message("a2", "assistant"),
  message("u2", "user"),
  message("a3", "assistant"),
];

describe("countMessagesAfter", () => {
  it("counts every message after the edited one, including its direct reply", () => {
    expect(countMessagesAfter(MESSAGES, "u1")).toBe(3);
  });

  it("counts only the direct reply when the edited message is the last user turn", () => {
    expect(countMessagesAfter(MESSAGES, "u2")).toBe(1);
  });

  it("is zero when nothing follows the edited message", () => {
    expect(countMessagesAfter([message("a1", "assistant"), message("u1", "user")], "u1")).toBe(0);
  });

  it("is zero when the message is not in the list", () => {
    expect(countMessagesAfter(MESSAGES, "missing")).toBe(0);
  });
});

describe("shouldConfirmEditTruncation", () => {
  it("does not ask when only the direct reply would be replaced", () => {
    expect(shouldConfirmEditTruncation(0)).toBe(false);
    expect(shouldConfirmEditTruncation(1)).toBe(false);
  });

  it("asks once anything beyond the direct reply would be removed", () => {
    expect(shouldConfirmEditTruncation(2)).toBe(true);
    expect(shouldConfirmEditTruncation(5)).toBe(true);
  });
});
