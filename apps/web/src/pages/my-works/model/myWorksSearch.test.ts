import { describe, expect, it } from "vitest";

import { isMyWorkTypeFilter, isMyWorksSort, myWorksSearchSchema, resolveMyWorksSearch } from "./myWorksSearch";

describe("myWorksSearchSchema", () => {
  it("파라미터가 없으면 전부 undefined다 — 기본값은 URL에 싣지 않는다", () => {
    expect(myWorksSearchSchema.parse({})).toEqual({});
  });

  it("정의된 값만 통과시킨다", () => {
    expect(myWorksSearchSchema.parse({ type: "unpublished", visibility: "link", sort: "latest" })).toEqual({
      type: "unpublished",
      visibility: "link",
      sort: "latest",
    });
    expect(myWorksSearchSchema.safeParse({ type: "all" }).success).toBe(false);
    expect(myWorksSearchSchema.safeParse({ visibility: "all" }).success).toBe(false);
  });
});

describe("resolveMyWorksSearch", () => {
  it("파라미터가 없으면 세 축 모두 기본값이다 — 기본값 규칙이 여기 하나뿐이다", () => {
    expect(resolveMyWorksSearch({})).toEqual({ type: "all", visibility: "all", sort: "latest" });
  });

  it("파라미터를 그대로 편다", () => {
    expect(resolveMyWorksSearch({ type: "story", visibility: "private", sort: "latest" })).toEqual({
      type: "story",
      visibility: "private",
      sort: "latest",
    });
  });

  it("미등록에서는 공개범위를 all로 눌러 둔다 — 손으로 만든 URL이 라벨만 좁혀 보이게 하면 안 된다", () => {
    expect(resolveMyWorksSearch({ type: "unpublished", visibility: "private" })).toEqual({
      type: "unpublished",
      visibility: "all",
      sort: "latest",
    });
  });
});

describe("술어", () => {
  it("isMyWorkTypeFilter는 칩 4종만 통과시킨다 — Radix가 흘리는 빈 문자열을 여기서 막는다", () => {
    expect(["all", "character", "story", "unpublished"].every(isMyWorkTypeFilter)).toBe(true);
    expect(isMyWorkTypeFilter("")).toBe(false);
    expect(isMyWorkTypeFilter("temp")).toBe(false);
  });

  it("isMyWorksSort는 최신순만 통과시킨다", () => {
    expect(isMyWorksSort("latest")).toBe(true);
    expect(isMyWorksSort("popular")).toBe(false);
  });
});
