import { describe, expect, it } from "vitest";

import type { NovelPermission } from "@/entities/content";

import { needsNovelPermissionChoice, novelPermissionPublishValue } from "./novelPermissionChoice";

const PERMISSIONS: NovelPermission[] = ["forbidden", "private", "public"];

describe("needsNovelPermissionChoice", () => {
  // 발행 이력 0(확인됨) ↔ 1 이상 ↔ 모름(조회 실패) × 저장값 셋 × 이번 화면에서 고름 여부.
  it.each([
    [0, "forbidden", false, true],
    [0, "forbidden", true, false],
    [0, "private", false, false],
    [0, "public", false, false],
    [1, "forbidden", false, false],
    [3, "forbidden", false, false],
    [1, "public", false, false],
    [undefined, "forbidden", false, true],
    [undefined, "forbidden", true, false],
    [undefined, "private", false, false],
  ] as const)("이력 %s · 저장값 %s · 고름 %s → %s", (publishedCount, savedPermission, chosen, expected) => {
    expect(needsNovelPermissionChoice({ publishedCount, savedPermission, chosen, alreadyAsked: false })).toBe(expected);
  });

  it("이미 고르라고 막았으면(서버 거절 포함) 이력·저장값과 상관없이 고를 때까지 묻는다", () => {
    for (const savedPermission of PERMISSIONS) {
      expect(needsNovelPermissionChoice({ publishedCount: 2, savedPermission, chosen: false, alreadyAsked: true })).toBe(true);
      expect(needsNovelPermissionChoice({ publishedCount: 2, savedPermission, chosen: true, alreadyAsked: true })).toBe(false);
    }
  });
});

describe("novelPermissionPublishValue", () => {
  it("이번 화면에서 고르면 이력과 상관없이 지금 값을 싣는다", () => {
    expect(novelPermissionPublishValue({ publishedCount: 0, savedPermission: "forbidden", chosen: true }, "forbidden")).toBe("forbidden");
    expect(novelPermissionPublishValue({ publishedCount: 2, savedPermission: "forbidden", chosen: true }, "public")).toBe("public");
  });

  it("고르지 않은 미발행 초안은 저장값이 넓힌 값일 때만 싣는다 — 허용 안 함 기본값은 고른 것이 아니다", () => {
    expect(novelPermissionPublishValue({ publishedCount: 0, savedPermission: "private", chosen: false }, "private")).toBe("private");
    expect(novelPermissionPublishValue({ publishedCount: undefined, savedPermission: "public", chosen: false }, "public")).toBe("public");
    expect(novelPermissionPublishValue({ publishedCount: 0, savedPermission: "forbidden", chosen: false }, "forbidden")).toBeUndefined();
  });

  it("고르지 않은 발행작은 싣지 않는다 — 지금 값을 그대로 둔다", () => {
    expect(novelPermissionPublishValue({ publishedCount: 1, savedPermission: "public", chosen: false }, "public")).toBeUndefined();
    expect(novelPermissionPublishValue({ publishedCount: 1, savedPermission: "forbidden", chosen: false }, "forbidden")).toBeUndefined();
  });
});
