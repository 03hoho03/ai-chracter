import { describe, expect, it } from "vitest";

import { toNovelReadProgress } from "./novelReadProgress";

describe("toNovelReadProgress", () => {
  it("다 읽은 화 수를 전체 화 수로 나눈다", () => {
    const progress = toNovelReadProgress([
      { ordinal: 1, finishedReading: true },
      { ordinal: 2, finishedReading: false },
      { ordinal: 3, finishedReading: false },
      { ordinal: 4, finishedReading: false },
    ]);
    expect(progress).toEqual({ finishedCount: 1, totalCount: 4, ratio: 0.25, lastFinishedOrdinal: 1 });
  });

  it("건너뛰며 읽었으면 '몇 화까지'는 다 읽은 화 중 가장 뒤 화다", () => {
    const progress = toNovelReadProgress([
      { ordinal: 1, finishedReading: true },
      { ordinal: 2, finishedReading: false },
      { ordinal: 3, finishedReading: true },
    ]);
    expect(progress.finishedCount).toBe(2);
    expect(progress.lastFinishedOrdinal).toBe(3);
  });

  it("목록 순서와 무관하게 센다", () => {
    expect(
      toNovelReadProgress([
        { ordinal: 3, finishedReading: true },
        { ordinal: 1, finishedReading: true },
      ]).lastFinishedOrdinal,
    ).toBe(3);
  });

  it("읽은 화가 없으면 0, 화가 없어도 0", () => {
    expect(toNovelReadProgress([{ ordinal: 1, finishedReading: false }])).toEqual({
      finishedCount: 0,
      totalCount: 1,
      ratio: 0,
      lastFinishedOrdinal: undefined,
    });
    expect(toNovelReadProgress([]).ratio).toBe(0);
  });
});
