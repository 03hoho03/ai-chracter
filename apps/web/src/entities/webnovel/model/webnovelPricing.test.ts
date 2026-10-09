import { describe, expect, it } from "vitest";

import { toLockedChapterSentence, toWebnovelPriceSummary } from "./webnovelPricing";

describe("toWebnovelPriceSummary", () => {
  it("names the free range and where paid chapters start", () => {
    expect(toWebnovelPriceSummary({ chapterCount: 8, freeChapterCount: 5, chapterPrice: 30 })).toBe(
      "1~5화 무료 · 6화부터 화당 30클로버",
    );
  });

  it("says everything is free while every published chapter is in the free range", () => {
    expect(toWebnovelPriceSummary({ chapterCount: 5, freeChapterCount: 5, chapterPrice: 30 })).toBe("모든 화 무료");
  });

  it("drops the free range when no chapter is free", () => {
    expect(toWebnovelPriceSummary({ chapterCount: 3, freeChapterCount: 0, chapterPrice: 30 })).toBe("화당 30클로버");
  });

  it("does not write a 1~1 range for a single free chapter", () => {
    expect(toWebnovelPriceSummary({ chapterCount: 4, freeChapterCount: 1, chapterPrice: 30 })).toBe(
      "1화 무료 · 2화부터 화당 30클로버",
    );
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
