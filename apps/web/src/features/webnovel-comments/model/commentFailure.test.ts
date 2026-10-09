import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { countVisibleCharacters, toCommentWriteError } from "./commentFailure";

function apiError(status: number, detail: string | Record<string, unknown> | undefined) {
  return new ApiErrorObject({ status, detail, message: "error" });
}

describe("toCommentWriteError", () => {
  it("코드마다 할 일을 말한다", () => {
    expect(toCommentWriteError(apiError(422, { code: "NOVEL_COMMENT_TOO_LONG" }))).toBe("댓글은 1,000자까지 쓸 수 있어요.");
    expect(toCommentWriteError(apiError(429, { code: "NOVEL_COMMENT_RATE_LIMITED", retryAfterSeconds: 30 }))).toContain("잠시 후");
    expect(toCommentWriteError(apiError(403, { code: "NOVEL_CHAPTER_LOCKED" }))).toBe("소장한 화에만 댓글을 남길 수 있어요.");
  });

  it("정지된 계정의 403 은 소장 문장이 아니다", () => {
    expect(toCommentWriteError(apiError(403, "Account suspended"))).toBe("지금 이 계정으로는 댓글을 남길 수 없어요.");
  });
});

describe("countVisibleCharacters", () => {
  it("결합된 이모지를 한 글자로 센다", () => {
    expect(countVisibleCharacters("가👨‍👩‍👧")).toBe(2);
  });
});
