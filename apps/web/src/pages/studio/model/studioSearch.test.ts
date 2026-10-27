import { describe, expect, it } from "vitest";

import { MY_WORKS_QUERY_MAX_LENGTH } from "@/entities/work";

import { resolveStudioSearch, studioSearchSchema } from "./studioSearch";

describe("studioSearchSchema", () => {
  it("아는 값은 그대로 받는다", () => {
    expect(studioSearchSchema.parse({ type: "novel", status: "review", q: "비 오는 밤" })).toEqual({
      type: "novel",
      status: "review",
      q: "비 오는 밤",
    });
  });

  it("모르는 값과 기본값 all 은 부재로 떨어뜨린다", () => {
    expect(studioSearchSchema.parse({ type: "unpublished", status: "all" })).toEqual({
      type: undefined,
      status: undefined,
      q: undefined,
    });
    expect(studioSearchSchema.parse({ type: "all", status: "bogus" })).toEqual({
      type: undefined,
      status: undefined,
      q: undefined,
    });
  });

  it("검색어는 보낼 꼴로 접는다 — 공백뿐이면 부재, 상한을 넘으면 자른다", () => {
    expect(studioSearchSchema.parse({ q: "   " }).q).toBeUndefined();
    expect(studioSearchSchema.parse({ q: "가".repeat(MY_WORKS_QUERY_MAX_LENGTH + 1) }).q).toBe(
      "가".repeat(MY_WORKS_QUERY_MAX_LENGTH),
    );
  });

  it("라우터가 숫자로 읽은 검색어(?q=1)도 검색어로 남긴다", () => {
    expect(studioSearchSchema.parse({ q: 1 }).q).toBe("1");
    expect(studioSearchSchema.parse({ q: 2024 }).q).toBe("2024");
  });

  it("검색어로 읽을 수 없는 값은 부재로 떨어뜨린다", () => {
    expect(studioSearchSchema.parse({ q: { nested: true } }).q).toBeUndefined();
  });
});

describe("resolveStudioSearch", () => {
  it("축이 없으면 서버 값 all 로 편다", () => {
    expect(resolveStudioSearch({}, true)).toEqual({ type: "all", status: "all", q: undefined });
  });

  it("소설 영역이 열린 계정은 소설 유형과 심사 중 상태를 그대로 보낸다", () => {
    expect(resolveStudioSearch({ type: "novel", status: "review", q: "밤" }, true)).toEqual({
      type: "novel",
      status: "review",
      q: "밤",
    });
  });

  it("소설 영역이 닫힌 계정은 소설 유형과 심사 중 상태를 전체로 접는다", () => {
    expect(resolveStudioSearch({ type: "novel", status: "review", q: "밤" }, false)).toEqual({
      type: "all",
      status: "all",
      q: "밤",
    });
  });

  it("소설 영역이 닫혀도 소설과 무관한 축은 남긴다", () => {
    expect(resolveStudioSearch({ type: "story", status: "changed" }, false)).toEqual({
      type: "story",
      status: "changed",
      q: undefined,
    });
  });
});
