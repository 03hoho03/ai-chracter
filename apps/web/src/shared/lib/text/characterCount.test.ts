import { describe, expect, it } from "vitest";

import { clampCharacters, countCharacters } from "./characterCount";

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

describe("clampCharacters", () => {
  it("keeps a value within the limit as it is and reports nothing cut", () => {
    expect(clampCharacters("첫 리딩", 20)).toEqual({ value: "첫 리딩", isTruncated: false });
  });

  it("keeps a value exactly at the limit without reporting a cut", () => {
    expect(clampCharacters("가".repeat(20), 20)).toEqual({ value: "가".repeat(20), isTruncated: false });
  });

  it("cuts a pasted value past the limit and reports the cut", () => {
    expect(clampCharacters(`${"가".repeat(19)}!!!`, 20)).toEqual({ value: `${"가".repeat(19)}!`, isTruncated: true });
  });

  it("counts an emoji as one character, the way the server does", () => {
    expect(clampCharacters("😀".repeat(3), 2)).toEqual({ value: "😀😀", isTruncated: true });
    expect(clampCharacters("😀😀", 2).isTruncated).toBe(false);
  });

  it("never splits an emoji in half", () => {
    // UTF-16 단위로 자르면 둘째 글자의 앞 반쪽만 남는다.
    expect(clampCharacters(`가${"😀".repeat(3)}`, 2).value).toBe("가😀");
    expect(`가${"😀".repeat(3)}`.slice(0, 2)).not.toBe("가😀");
  });
});
