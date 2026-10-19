import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { toMakeChapterFreeFailure } from "./makeChapterFreeFailure";

function apiError(status: number, detail: Record<string, unknown>) {
  return new ApiErrorObject({ status, detail, message: "error" });
}

describe("toMakeChapterFreeFailure", () => {
  it("공개한 화가 아니게 됐거나 스위치가 꺼졌으면 화면이 낡았다", () => {
    expect(toMakeChapterFreeFailure(apiError(404, { code: "NOVEL_CHAPTER_NOT_FOUND" }))).toBe("stale");
    expect(toMakeChapterFreeFailure(apiError(409, { code: "NOVEL_PRICE_CHOICE_DISABLED" }))).toBe("stale");
  });

  it("그 밖은 다시 해 볼 수 있는 실패다", () => {
    expect(toMakeChapterFreeFailure(apiError(500, { code: "INTERNAL" }))).toBe("failed");
    expect(toMakeChapterFreeFailure(new Error("network"))).toBe("failed");
  });
});
