import { describe, expect, it } from "vitest";

import { toPublishedPriceRows, toPublishPriceRows, toRepublishOrdinals } from "./publishPricing";

function status(patch: Partial<Parameters<typeof toPublishPriceRows>[0]>): Parameters<typeof toPublishPriceRows>[0] {
  return { publishedChapterCount: 0, publishedChapters: [], freeLockedOrdinals: [], changedChapterOrdinals: [], ...patch };
}

describe("toPublishPriceRows", () => {
  it("처음 공개는 앞 화를 빼고 고른 끝 화까지 새 화마다 가격을 고른다", () => {
    expect(toPublishPriceRows(status({}), { freeChapterCount: 5, targetOrdinal: 8 })).toEqual([
      { kind: "choice", ordinal: 6 },
      { kind: "choice", ordinal: 7 },
      { kind: "choice", ordinal: 8 },
    ]);
  });

  it("끝 화를 줄이면 줄도 줄고, 앞 화까지만 고르면 줄이 없다", () => {
    expect(toPublishPriceRows(status({}), { freeChapterCount: 5, targetOrdinal: 6 })).toEqual([{ kind: "choice", ordinal: 6 }]);
    expect(toPublishPriceRows(status({}), { freeChapterCount: 5, targetOrdinal: 5 })).toEqual([]);
  });

  it("무료 고정 번호는 고를 것 없이 무료로 고정한다", () => {
    expect(toPublishPriceRows(status({ freeLockedOrdinals: [7] }), { freeChapterCount: 5, targetOrdinal: 8 })).toEqual([
      { kind: "choice", ordinal: 6 },
      { kind: "locked", ordinal: 7 },
      { kind: "choice", ordinal: 8 },
    ]);
  });

  it("다시 내는 고친 화는 지금 가격을 글로만 두고 새 화는 공개한 범위 다음부터다", () => {
    const published = status({
      publishedChapterCount: 7,
      publishedChapters: [
        { chapterId: "c3", ordinal: 3, price: 0 },
        { chapterId: "c6", ordinal: 6, price: 30 },
        { chapterId: "c7", ordinal: 7, price: 0 },
      ],
      changedChapterOrdinals: [7, 3, 6, 9],
    });
    expect(toPublishPriceRows(published, { freeChapterCount: 5, targetOrdinal: 9 })).toEqual([
      { kind: "kept", ordinal: 6, price: 30 },
      { kind: "kept", ordinal: 7, price: 0 },
      { kind: "choice", ordinal: 8 },
      { kind: "choice", ordinal: 9 },
    ]);
  });
});

describe("toRepublishOrdinals", () => {
  it("공개한 범위 안의 고친 화만 번호 순으로", () => {
    expect(toRepublishOrdinals({ publishedChapterCount: 6, changedChapterOrdinals: [6, 2, 7] })).toEqual([2, 6]);
  });
});

describe("toPublishedPriceRows", () => {
  it("앞 화를 빼고 번호 순으로", () => {
    expect(
      toPublishedPriceRows(
        [
          { chapterId: "c7", ordinal: 7, price: 0 },
          { chapterId: "c2", ordinal: 2, price: 0 },
          { chapterId: "c5", ordinal: 5, price: 0 },
          { chapterId: "c6", ordinal: 6, price: 30 },
        ],
        5,
      ).map((row) => row.ordinal),
    ).toEqual([6, 7]);
  });
});
