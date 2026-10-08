import { describe, expect, it } from "vitest";

import { toRestoreParagraphIndex } from "./toRestoreParagraphIndex";

describe("toRestoreParagraphIndex", () => {
  it("문단 수가 같으면 저장된 인덱스를 그대로 쓴다", () => {
    expect(toRestoreParagraphIndex({ paragraphIndex: 7, paragraphCount: 20 }, 20)).toBe(7);
  });

  it("문단 수가 바뀌었으면 같은 비율 지점으로 근사한다", () => {
    expect(toRestoreParagraphIndex({ paragraphIndex: 10, paragraphCount: 20 }, 40)).toBe(20);
    expect(toRestoreParagraphIndex({ paragraphIndex: 10, paragraphCount: 40 }, 20)).toBe(5);
    // 3 × 10 / 7 = 4.28… → 4, 5 × 10 / 7 = 7.14… → 7
    expect(toRestoreParagraphIndex({ paragraphIndex: 3, paragraphCount: 7 }, 10)).toBe(4);
    expect(toRestoreParagraphIndex({ paragraphIndex: 5, paragraphCount: 7 }, 10)).toBe(7);
    // 1 × 5 / 2 = 2.5 → 3 (Math.round 는 .5 를 올린다)
    expect(toRestoreParagraphIndex({ paragraphIndex: 1, paragraphCount: 2 }, 5)).toBe(3);
  });

  it("반올림한 근사가 지금 본문의 끝을 넘으면 마지막 문단으로 자른다", () => {
    // 9 × 5 / 10 = 4.5 → 5 → 마지막 인덱스 4
    expect(toRestoreParagraphIndex({ paragraphIndex: 9, paragraphCount: 10 }, 5)).toBe(4);
    expect(toRestoreParagraphIndex({ paragraphIndex: 19, paragraphCount: 20 }, 2)).toBe(1);
  });

  it("문단 수가 같아도 범위 밖 인덱스는 본문 안으로 자른다", () => {
    expect(toRestoreParagraphIndex({ paragraphIndex: 25, paragraphCount: 10 }, 10)).toBe(9);
    expect(toRestoreParagraphIndex({ paragraphIndex: -3, paragraphCount: 10 }, 10)).toBe(0);
  });

  it("그때 문단 수가 0 이하면 비율을 못 내므로 인덱스를 잘라서 쓴다", () => {
    expect(toRestoreParagraphIndex({ paragraphIndex: 4, paragraphCount: 0 }, 10)).toBe(4);
    expect(toRestoreParagraphIndex({ paragraphIndex: 40, paragraphCount: 0 }, 10)).toBe(9);
  });

  it("지금 본문이 비었으면 0", () => {
    expect(toRestoreParagraphIndex({ paragraphIndex: 4, paragraphCount: 10 }, 0)).toBe(0);
  });
});
