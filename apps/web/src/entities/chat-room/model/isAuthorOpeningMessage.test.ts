import { describe, expect, it } from "vitest";

import { isAuthorOpeningMessage, isAuthorTextMessage } from "./isAuthorOpeningMessage";

describe("isAuthorOpeningMessage", () => {
  it("is the first assistant message of a story room", () => {
    expect(isAuthorOpeningMessage({ index: 0, role: "assistant", contentType: "story" })).toBe(true);
  });

  it("is the first message once every older message is loaded", () => {
    expect(isAuthorOpeningMessage({ index: 0, role: "assistant", contentType: "story", hasMoreBefore: false })).toBe(true);
  });

  it.each([
    ["a later assistant message", { index: 1, role: "assistant", contentType: "story" }],
    ["a user message in first place", { index: 0, role: "user", contentType: "story" }],
    ["a character greeting", { index: 0, role: "assistant", contentType: "character" }],
    // 긴 방의 꼬리 창 — 첫 자리의 모델 응답은 작성자 글이 아니다.
    ["the first loaded message while older ones are still unloaded", { index: 0, role: "assistant", contentType: "story", hasMoreBefore: true }],
  ] as const)("is not %s", (_name, position) => {
    expect(isAuthorOpeningMessage(position)).toBe(false);
  });
});

describe("isAuthorTextMessage", () => {
  it("is the first assistant message of any room, character greetings included", () => {
    expect(isAuthorTextMessage({ index: 0, role: "assistant" })).toBe(true);
  });

  it.each([
    ["a later assistant message", { index: 1, role: "assistant" }],
    ["a user message in first place", { index: 0, role: "user" }],
    ["the first loaded message while older ones are still unloaded", { index: 0, role: "assistant", hasMoreBefore: true }],
  ] as const)("is not %s", (_name, position) => {
    expect(isAuthorTextMessage(position)).toBe(false);
  });
});
