import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../api/chatStream";
import { canRestorePreviousResponse } from "./canRestorePreviousResponse";

const user: ChatMessage = { id: "u1", role: "user", content: "안녕", createdAt: "2026-10-15T00:00:00Z" };
const regenerated: ChatMessage = { id: "a2", role: "assistant", content: "새 답", createdAt: "2026-10-15T00:01:00Z" };
const nextUser: ChatMessage = { id: "u2", role: "user", content: "다음", createdAt: "2026-10-15T00:02:00Z" };

describe("canRestorePreviousResponse", () => {
  it("서버가 되돌릴 수 있다고 한 AI 응답이 마지막 메시지면 참이다", () => {
    expect(canRestorePreviousResponse({ previousResponseFor: "a2", messages: [user, regenerated] }, regenerated)).toBe(true);
  });

  it("다른 메시지·되돌릴 답이 없는 방·사용자 메시지는 거짓이다", () => {
    const messages = [user, regenerated];
    expect(canRestorePreviousResponse({ previousResponseFor: "a2", messages }, { id: "a1", role: "assistant" })).toBe(false);
    expect(canRestorePreviousResponse({ previousResponseFor: undefined, messages }, regenerated)).toBe(false);
    expect(canRestorePreviousResponse({ previousResponseFor: "u1", messages: [user] }, user)).toBe(false);
  });

  it("그 뒤에 사용자 메시지가 붙었으면(보내기가 실패해 방을 다시 받지 않았다) 거짓이다", () => {
    expect(
      canRestorePreviousResponse({ previousResponseFor: "a2", messages: [user, regenerated, nextUser] }, regenerated),
    ).toBe(false);
  });
});
