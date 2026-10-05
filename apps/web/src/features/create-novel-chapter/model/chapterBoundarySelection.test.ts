import { describe, expect, it } from "vitest";

import { toInitialChapterEnd } from "./chapterBoundarySelection";

const candidates = [{ messageId: "a" }, { messageId: "b" }, { messageId: "c" }];

describe("toInitialChapterEnd", () => {
  it("제안이 후보 안에 있으면 그 턴을 골라 둔다", () => {
    expect(toInitialChapterEnd({ candidates, suggestion: { endMessageId: "b" } })).toBe("b");
  });

  it("제안이 없으면(모델 실패) 아무것도 고르지 않는다", () => {
    expect(toInitialChapterEnd({ candidates, suggestion: null })).toBeUndefined();
  });

  it("제안이 후보 밖을 가리키면 아무것도 고르지 않는다 — 다른 턴으로 대신 고르지 않는다", () => {
    expect(toInitialChapterEnd({ candidates, suggestion: { endMessageId: "z" } })).toBeUndefined();
  });
});
