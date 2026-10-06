import { describe, expect, it } from "vitest";

import {
  clampParagraphRange,
  formatParagraphRange,
  nextParagraphRange,
  toParagraphSelectionAnnouncement,
} from "./paragraphRange";

describe("nextParagraphRange", () => {
  it("고른 것이 없으면 그 문단 하나를 고른다", () => {
    expect(nextParagraphRange(null, 3)).toEqual({ start: 3, end: 3 });
  });

  it("범위 바로 뒤를 누르면 한 칸 늘린다", () => {
    expect(nextParagraphRange({ start: 2, end: 3 }, 4)).toEqual({ start: 2, end: 4 });
  });

  it("범위 바로 앞을 누르면 앞으로 한 칸 늘린다", () => {
    expect(nextParagraphRange({ start: 2, end: 3 }, 1)).toEqual({ start: 1, end: 3 });
  });

  it("떨어진 문단을 누르면 사이 문단까지 모두 넣는다", () => {
    expect(nextParagraphRange({ start: 1, end: 1 }, 5)).toEqual({ start: 1, end: 5 });
    expect(nextParagraphRange({ start: 4, end: 6 }, 0)).toEqual({ start: 0, end: 6 });
  });

  it("범위 안을 누르면 그 문단 하나로 다시 시작한다", () => {
    expect(nextParagraphRange({ start: 2, end: 5 }, 4)).toEqual({ start: 4, end: 4 });
    expect(nextParagraphRange({ start: 2, end: 5 }, 2)).toEqual({ start: 2, end: 2 });
  });

  it("하나만 고른 문단을 다시 누르면 푼다", () => {
    expect(nextParagraphRange({ start: 3, end: 3 }, 3)).toBeNull();
  });

  it("Shift 로 범위 밖을 누르면 늘린다", () => {
    expect(nextParagraphRange({ start: 2, end: 2 }, 6, { extend: true })).toEqual({ start: 2, end: 6 });
    expect(nextParagraphRange(null, 6, { extend: true })).toEqual({ start: 6, end: 6 });
  });

  it("Shift 로 범위 안을 누르면 다시 시작하지 않고 끝을 그 문단으로 옮긴다", () => {
    expect(nextParagraphRange({ start: 2, end: 6 }, 4, { extend: true })).toEqual({ start: 2, end: 4 });
  });

  it("Shift 로 하나만 고른 문단을 다시 눌러도 풀지 않는다", () => {
    expect(nextParagraphRange({ start: 3, end: 3 }, 3, { extend: true })).toEqual({ start: 3, end: 3 });
  });
});

describe("clampParagraphRange", () => {
  it("문단 수가 줄면 남은 문단 안으로 접는다", () => {
    expect(clampParagraphRange({ start: 4, end: 7 }, 6)).toEqual({ start: 4, end: 5 });
    expect(clampParagraphRange({ start: 8, end: 9 }, 6)).toEqual({ start: 5, end: 5 });
  });

  it("문단 안에 있으면 그대로 둔다", () => {
    expect(clampParagraphRange({ start: 1, end: 2 }, 6)).toEqual({ start: 1, end: 2 });
  });

  it("문단이 없으면 범위도 없다", () => {
    expect(clampParagraphRange({ start: 0, end: 0 }, 0)).toBeNull();
    expect(clampParagraphRange(null, 3)).toBeNull();
  });
});

describe("formatParagraphRange", () => {
  it("화면 번호는 1부터다", () => {
    expect(formatParagraphRange({ start: 2, end: 4 })).toBe("3~5번째 문단");
    expect(formatParagraphRange({ start: 0, end: 0 })).toBe("1번째 문단");
  });

  it("알림 문장은 범위를 말하고, 없으면 없다고 말한다", () => {
    expect(toParagraphSelectionAnnouncement({ start: 2, end: 4 })).toBe("3~5번째 문단을 골랐어요.");
    expect(toParagraphSelectionAnnouncement(null)).toBe("고른 문단이 없어요.");
  });
});
