import { describe, expect, it } from "vitest";

import { clampAtCaret, countCharacters } from "./characterCount";

describe("countCharacters", () => {
  it("counts an emoji as one character, the way the server does", () => {
    expect(countCharacters("가😀")).toBe(2);
    expect("가😀".length).toBe(3);
  });

  it("counts every code point of a joined emoji and a combining mark, as the server does", () => {
    // 가족 이모지는 사람 셋과 잇는 글자 둘, 결합 악센트는 바탕 글자와 따로 센다.
    expect(countCharacters("👨‍👩‍👧")).toBe(5);
    expect(countCharacters("é")).toBe(2);
  });

  it("does not trim surrounding spaces", () => {
    expect(countCharacters(" 가 ")).toBe(3);
  });
});

describe("clampAtCaret", () => {
  it("keeps a value within or exactly at the limit as it is", () => {
    expect(clampAtCaret("첫 리딩", 4, 20)).toEqual({ value: "첫 리딩", caret: 4, isTruncated: false });
    expect(clampAtCaret("가".repeat(20), 20, 20)).toEqual({ value: "가".repeat(20), caret: 20, isTruncated: false });
  });

  it("drops the overflow from what was just typed at the end", () => {
    // 꽉 찬 "가나다" 끝에 "라" 를 쳤다.
    expect(clampAtCaret("가나다라", 4, 3)).toEqual({ value: "가나다", caret: 3, isTruncated: true });
  });

  it("keeps the original tail when typing in the middle of a full field", () => {
    // 꽉 찬 "가나다" 의 "가" 뒤에 "X" 를 쳤다 — 끝의 "다" 가 아니라 방금 친 "X" 를 덜어낸다.
    expect(clampAtCaret("가X나다", 2, 3)).toEqual({ value: "가나다", caret: 1, isTruncated: true });
  });

  it("keeps only as much of a paste in the middle as fits, and leaves the caret after it", () => {
    // "가나다라"(상한 6) 의 "가" 뒤에 "12345" 를 붙여넣었다 — 두 글자만 들어갈 자리다.
    expect(clampAtCaret("가12345나다라", 6, 6)).toEqual({ value: "가12나다라", caret: 3, isTruncated: true });
  });

  it("treats a paste over a selection the same way, after the browser has replaced it", () => {
    // "가나다라"(상한 4) 에서 "나다" 를 골라 "XYZ" 를 붙여넣으면 브라우저가 "가XYZ라" 로 바꾸고 커서는 Z 뒤다.
    expect(clampAtCaret("가XYZ라", 4, 4)).toEqual({ value: "가XY라", caret: 3, isTruncated: true });
  });

  it("drops whole emoji, never half of one, and returns the caret in UTF-16 units", () => {
    // "가나"(상한 3) 사이에 이모지 둘을 붙여넣었다 — 하나만 들어가고 커서는 그 뒤(UTF-16 으로 3)다.
    expect(clampAtCaret("가😀😀나", 5, 3)).toEqual({ value: "가😀나", caret: 3, isTruncated: true });
    // 커서가 이모지 한가운데(UTF-16 으로 4)에 있어도 이모지를 쪼개지 않는다.
    expect(clampAtCaret("가😀😀나", 4, 3).value).toBe("가😀나");
  });

  it("cuts the end when a value saved over the limit has nothing before the caret to drop", () => {
    expect(clampAtCaret("가나다라", 0, 2)).toEqual({ value: "가나", caret: 0, isTruncated: true });
  });
});
