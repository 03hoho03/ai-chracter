import { describe, expect, it } from "vitest";

import type { WebnovelChapterAccess } from "../api/useWebnovelQuery";
import { toLockedChapterSentence, toWebnovelPriceSummary } from "./webnovelPricing";

type Access = WebnovelChapterAccess;

/** 1화부터 `count` 화까지 — 무료 범위 안은 `free`, 그 뒤는 `overrides` 가 없으면 `locked`. */
function chapters(count: number, freeChapterCount: number, overrides: Record<number, Access> = {}) {
  return Array.from({ length: count }, (_, index) => {
    const ordinal = index + 1;
    const access: Access = overrides[ordinal] ?? (ordinal <= freeChapterCount ? "free" : "locked");
    return { ordinal, access };
  });
}

describe("toWebnovelPriceSummary", () => {
  it("names the free range and where paid chapters start", () => {
    expect(toWebnovelPriceSummary({ chapters: chapters(8, 5), freeChapterCount: 5, chapterPrice: 30 })).toBe(
      "1~5화 무료 · 6화부터 화당 30클로버",
    );
  });

  it("says everything is free while every published chapter is in the free range", () => {
    expect(toWebnovelPriceSummary({ chapters: chapters(5, 5), freeChapterCount: 5, chapterPrice: 30 })).toBe("모든 화 무료");
  });

  it("drops the free range when no chapter is free", () => {
    expect(toWebnovelPriceSummary({ chapters: chapters(3, 0), freeChapterCount: 0, chapterPrice: 30 })).toBe("화당 30클로버");
  });

  it("does not write a 1~1 range for a single free chapter", () => {
    expect(toWebnovelPriceSummary({ chapters: chapters(4, 1), freeChapterCount: 1, chapterPrice: 30 })).toBe(
      "1화 무료 · 2화부터 화당 30클로버",
    );
  });

  it("작가가 무료 범위 뒤에 무료로 둔 화가 있으면 일부 화 무료를 덧붙인다", () => {
    expect(
      toWebnovelPriceSummary({ chapters: chapters(8, 5, { 7: "free" }), freeChapterCount: 5, chapterPrice: 30 }),
    ).toBe("1~5화 무료 · 6화부터 화당 30클로버, 일부 화 무료");
  });

  it("소장한 유료 화는 무료로 세지 않는다", () => {
    expect(
      toWebnovelPriceSummary({ chapters: chapters(8, 5, { 6: "owned", 7: "owned" }), freeChapterCount: 5, chapterPrice: 30 }),
    ).toBe("1~5화 무료 · 6화부터 화당 30클로버");
  });

  it("무료 범위 안의 화는 무료여도 덧붙이는 근거가 아니다(무료 화 수와 같은 번호 포함)", () => {
    expect(toWebnovelPriceSummary({ chapters: chapters(6, 5), freeChapterCount: 5, chapterPrice: 30 })).toBe(
      "1~5화 무료 · 6화부터 화당 30클로버",
    );
  });

  it("무료 범위 뒤 화가 모두 무료면 모든 화 무료다", () => {
    expect(
      toWebnovelPriceSummary({ chapters: chapters(7, 5, { 6: "free", 7: "free" }), freeChapterCount: 5, chapterPrice: 30 }),
    ).toBe("모든 화 무료");
  });

  it("무료 범위가 없어도 무료 화가 있으면 덧붙인다", () => {
    expect(
      toWebnovelPriceSummary({ chapters: chapters(3, 0, { 2: "free" }), freeChapterCount: 0, chapterPrice: 30 }),
    ).toBe("화당 30클로버, 일부 화 무료");
  });
});

describe("toLockedChapterSentence", () => {
  it("explains the free range before the per-chapter purchase", () => {
    expect(toLockedChapterSentence(5)).toBe("이 소설은 1~5화가 무료이고, 6화부터는 화마다 소장해서 읽어요.");
  });

  it("skips the free range when nothing is free", () => {
    expect(toLockedChapterSentence(0)).toBe("이 소설은 화마다 소장해서 읽어요.");
  });
});
