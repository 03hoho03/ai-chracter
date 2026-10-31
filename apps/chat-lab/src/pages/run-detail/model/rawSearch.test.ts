import { describe, expect, it } from "vitest";

import { findMatches, splitByMatches, stepMatch } from "./rawSearch";

describe("findMatches", () => {
  it("대소문자를 가리지 않고 원문의 자리로 돌려준다", () => {
    expect(findMatches("Role <role> ROLE", "role")).toEqual([
      { start: 0, end: 4 },
      { start: 6, end: 10 },
      { start: 12, end: 16 },
    ]);
  });

  it("빈 검색어나 공백뿐인 검색어는 일치가 없다", () => {
    expect(findMatches("편지", "")).toEqual([]);
    expect(findMatches("편지", "  ")).toEqual([]);
  });

  it("정규식 기호를 글자 그대로 찾는다", () => {
    expect(findMatches("a.b axb", "a.b")).toEqual([{ start: 0, end: 3 }]);
  });

  it("겹치는 일치는 앞에서부터 하나씩만 센다", () => {
    expect(findMatches("aaaa", "aa")).toEqual([
      { start: 0, end: 2 },
      { start: 2, end: 4 },
    ]);
  });

  it("한글 검색어도 찾는다", () => {
    expect(findMatches("편지는 그 다음 주부터 썼어요. 편지", "편지")).toHaveLength(2);
  });
});

describe("stepMatch", () => {
  it("다음·이전으로 돌고 끝에서 처음으로 넘어간다", () => {
    expect(stepMatch(0, 3, 1)).toBe(1);
    expect(stepMatch(2, 3, 1)).toBe(0);
    expect(stepMatch(0, 3, -1)).toBe(2);
  });

  it("아직 고른 일치가 없으면 다음은 첫 일치, 이전은 마지막 일치", () => {
    expect(stepMatch(-1, 3, 1)).toBe(0);
    expect(stepMatch(-1, 3, -1)).toBe(2);
  });

  it("일치가 없으면 고를 것이 없다", () => {
    expect(stepMatch(0, 0, 1)).toBe(-1);
  });
});

describe("splitByMatches", () => {
  it("일치 사이 글과 일치를 차례로 나누고 지금 일치를 따로 표시한다", () => {
    const text = "ab편지cd편지";
    const matches = findMatches(text, "편지");

    expect(splitByMatches(text, matches, 1)).toEqual([
      { text: "ab", kind: "plain" },
      { text: "편지", kind: "match" },
      { text: "cd", kind: "plain" },
      { text: "편지", kind: "current" },
    ]);
  });

  it("일치가 없으면 원문 한 조각", () => {
    expect(splitByMatches("원문", [], -1)).toEqual([{ text: "원문", kind: "plain" }]);
  });
});
