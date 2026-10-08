import { describe, expect, it } from "vitest";

import { toChapterEndAfterModelChange, toInitialChapterEnd } from "./chapterBoundarySelection";

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

describe("toChapterEndAfterModelChange", () => {
  const shorter = [{ messageId: "a" }, { messageId: "b" }];

  it("고른 턴이 새 모델의 후보에도 있으면 그대로 둔다", () => {
    expect(toChapterEndAfterModelChange("b", { candidates, suggestion: { endMessageId: "a" } })).toBe("b");
  });

  // 턴을 덜 담는 모델로 바꾸면 고른 턴이 목록에서 빠진다 — 그 모델이 담을 수 있는 마지막 턴으로 당긴다.
  it("고른 턴이 새 목록 밖이면 그 모델의 마지막 후보로 당긴다", () => {
    expect(toChapterEndAfterModelChange("c", { candidates: shorter, suggestion: { endMessageId: "a" } })).toBe("b");
  });

  it("아직 안 골랐으면 새 제안을 골라 둔다", () => {
    expect(toChapterEndAfterModelChange(undefined, { candidates: shorter, suggestion: { endMessageId: "a" } })).toBe("a");
    expect(toChapterEndAfterModelChange(undefined, { candidates: shorter, suggestion: null })).toBeUndefined();
  });

  it("새 목록이 비면 고를 턴이 없다", () => {
    expect(toChapterEndAfterModelChange("c", { candidates: [], suggestion: null })).toBeUndefined();
  });
});
