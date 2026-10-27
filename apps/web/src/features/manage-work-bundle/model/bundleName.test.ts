import { describe, expect, it } from "vitest";

import { WORK_BUNDLE_NAME_MAX_LENGTH } from "@/entities/work";

import { countBundleNameChars, workBundleNameSchema } from "./bundleName";

function isValid(name: string): boolean {
  return workBundleNameSchema.safeParse({ name }).success;
}

describe("workBundleNameSchema", () => {
  it("공백만이면 거절한다", () => {
    expect(isValid("   ")).toBe(false);
    expect(isValid("")).toBe(false);
  });

  it("앞뒤 공백을 걷은 뒤 상한까지 받는다", () => {
    expect(isValid(`  ${"가".repeat(WORK_BUNDLE_NAME_MAX_LENGTH)}  `)).toBe(true);
    expect(isValid("가".repeat(WORK_BUNDLE_NAME_MAX_LENGTH + 1))).toBe(false);
  });

  it("글자 수는 서버처럼 코드 포인트로 센다 — 이모지 상한 개는 통과, 하나 더면 거절", () => {
    expect(isValid("🌧".repeat(WORK_BUNDLE_NAME_MAX_LENGTH))).toBe(true);
    expect(isValid("🌧".repeat(WORK_BUNDLE_NAME_MAX_LENGTH + 1))).toBe(false);
  });
});

describe("countBundleNameChars", () => {
  it("앞뒤 공백을 빼고 코드 포인트로 센다", () => {
    expect(countBundleNameChars("  🌧비  ")).toBe(2);
  });
});
