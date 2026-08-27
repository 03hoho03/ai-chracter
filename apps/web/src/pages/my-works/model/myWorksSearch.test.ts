import { describe, expect, it } from "vitest";

import { isMyWorkTypeFilter, isMyWorksSort, myWorksSearchSchema, resolveMyWorksSearch } from "./myWorksSearch";

describe("myWorksSearchSchema", () => {
  it("파라미터가 없으면 전부 undefined다 — 기본값은 URL에 싣지 않는다", () => {
    expect(myWorksSearchSchema.parse({})).toEqual({});
  });

  it("정의된 값을 그대로 통과시킨다", () => {
    expect(myWorksSearchSchema.parse({ type: "unpublished", visibility: "link", sort: "latest" })).toEqual({
      type: "unpublished",
      visibility: "link",
      sort: "latest",
    });
  });

  it("모르는 값은 그 축만 부재로 떨어뜨린다 — 던지면 라우터가 페이지를 통째로 죽인다", () => {
    // 기본값 멤버(`all`)도 `.exclude()` 때문에 '모르는 값'이다 — 부재로 접히므로 결과는 같다.
    expect(myWorksSearchSchema.parse({ type: "all" })).toEqual({});
    expect(myWorksSearchSchema.parse({ visibility: "all" })).toEqual({});
    expect(myWorksSearchSchema.parse({ type: "bogus", sort: "bogus" })).toEqual({});
    // 값 하나가 어긋나도 나머지 축은 살아남는다.
    expect(myWorksSearchSchema.parse({ type: "bogus", visibility: "private" })).toEqual({
      visibility: "private",
    });
    // 라우터는 `?type=1`을 숫자로 파싱해 넘긴다(`parseSearchWith(JSON.parse)`) — 타입이 어긋난 값도 같다.
    expect(myWorksSearchSchema.parse({ type: 1, visibility: null })).toEqual({});
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
