import { describe, expect, it } from "vitest";

import {
  PIN_CHAPTER_NAVIGATE_OPTIONS,
  novelSearchSchema,
  resolveSelectedChapter,
  toChapterSearchValue,
  toPinnedChapterSearchValue,
} from "./novelChapterSearch";

const CHAPTERS = [{ ordinal: 1 }, { ordinal: 2 }, { ordinal: 3 }];

describe("novelSearchSchema", () => {
  it.each([
    [{ chapter: 2 }, { chapter: 2 }],
    [{}, { chapter: undefined }],
    [{ chapter: "2" }, { chapter: undefined }],
    [{ chapter: 0 }, { chapter: undefined }],
    [{ chapter: 1.5 }, { chapter: undefined }],
    [{ chapter: null }, { chapter: undefined }],
  ])("%j → %j (어긋난 값은 던지지 않고 부재로 접힌다)", (input, expected) => {
    expect(novelSearchSchema.parse(input)).toEqual(expected);
  });
});

describe("resolveSelectedChapter", () => {
  it("부재면 마지막 장이다", () => {
    expect(resolveSelectedChapter(CHAPTERS, undefined)).toEqual({ ordinal: 3 });
  });

  it("있는 번호면 그 장이다", () => {
    expect(resolveSelectedChapter(CHAPTERS, 1)).toEqual({ ordinal: 1 });
  });

  it("없는 번호(지운 마지막 장)는 마지막 장으로 간다", () => {
    expect(resolveSelectedChapter(CHAPTERS, 4)).toEqual({ ordinal: 3 });
  });

  it("배열 순서가 아니라 번호로 마지막을 고른다", () => {
    expect(resolveSelectedChapter([{ ordinal: 2 }, { ordinal: 1 }], undefined)).toEqual({ ordinal: 2 });
  });

  it("장이 없으면 undefined 다", () => {
    expect(resolveSelectedChapter([], undefined)).toBeUndefined();
    expect(resolveSelectedChapter([], 2)).toBeUndefined();
  });
});

describe("toChapterSearchValue", () => {
  it("마지막 장은 주소에 싣지 않는다", () => {
    expect(toChapterSearchValue(CHAPTERS, 3)).toBeUndefined();
  });

  it("그 밖의 장은 번호를 싣는다", () => {
    expect(toChapterSearchValue(CHAPTERS, 1)).toBe(1);
  });
});

describe("toPinnedChapterSearchValue", () => {
  it("주소에 장 번호가 없는데 고치던 글이 생기면 보고 있는 장 번호를 주소에 박는다", () => {
    expect(toPinnedChapterSearchValue({ requested: undefined, selectedOrdinal: 3, isDraftDirty: true })).toBe(3);
  });

  it("주소에 이미 장 번호가 있으면 다시 박지 않는다", () => {
    expect(toPinnedChapterSearchValue({ requested: 2, selectedOrdinal: 2, isDraftDirty: true })).toBeUndefined();
  });

  it("고치던 글이 없으면 마지막 장을 따라가는 기본 주소를 그대로 둔다", () => {
    expect(toPinnedChapterSearchValue({ requested: undefined, selectedOrdinal: 3, isDraftDirty: false })).toBeUndefined();
  });

  it("보고 있는 장이 없으면(장이 하나도 없음) 박을 것이 없다", () => {
    expect(toPinnedChapterSearchValue({ requested: undefined, selectedOrdinal: undefined, isDraftDirty: true })).toBeUndefined();
  });
});

describe("PIN_CHAPTER_NAVIGATE_OPTIONS", () => {
  it("장 번호 박기는 기록을 쌓지 않고 창 스크롤을 맨 위로 올리지 않는다", () => {
    expect(PIN_CHAPTER_NAVIGATE_OPTIONS).toEqual({ replace: true, resetScroll: false });
  });
});
