import { describe, expect, it } from "vitest";

import { HOME_FILTER_RESET, hasHomeFilter, homeSearchSchema } from "./homeSearch";

describe("homeSearchSchema", () => {
  it("파라미터가 없으면 전부 undefined다 — 스토리·최신순은 URL에 싣지 않는다", () => {
    expect(homeSearchSchema.parse({})).toEqual({});
  });

  it("?type=character 는 그대로 통과한다", () => {
    expect(homeSearchSchema.parse({ type: "character" })).toEqual({ type: "character" });
  });

  it("?type=story 는 부재로 접힌다 — 기본값은 파라미터의 부재로만 표현한다", () => {
    expect(homeSearchSchema.parse({ type: "story" })).toEqual({});
  });

  it("모르는 type 은 그 축만 부재로 떨어뜨린다", () => {
    expect(homeSearchSchema.parse({ type: "bogus", genre: "g1" })).toEqual({ genre: "g1" });
    // 라우터는 `?type=1` 을 숫자로 파싱해 넘긴다.
    expect(homeSearchSchema.parse({ type: 1 })).toEqual({});
  });

  it("옛 ?sort=genre 링크는 최신순(부재)으로 열린다", () => {
    expect(homeSearchSchema.parse({ sort: "genre" })).toEqual({});
    expect(homeSearchSchema.parse({ sort: "popular" })).toEqual({ sort: "popular" });
  });
});

describe("hasHomeFilter", () => {
  it("유형과 정렬만 있으면 거르는 조건이 없다", () => {
    expect(hasHomeFilter({})).toBe(false);
    expect(hasHomeFilter({ type: "character", sort: "popular" })).toBe(false);
  });

  it("장르·검색어·작가·해시태그 중 하나라도 있으면 조건이 있다", () => {
    expect(hasHomeFilter({ genre: "g1" })).toBe(true);
    expect(hasHomeFilter({ q: "엘리" })).toBe(true);
    expect(hasHomeFilter({ creator: "u1" })).toBe(true);
    expect(hasHomeFilter({ hashtag: "로맨스" })).toBe(true);
  });

  it("HOME_FILTER_RESET 을 덮으면 조건이 남지 않고 유형·정렬은 그대로다", () => {
    const search = { type: "character" as const, sort: "popular" as const, genre: "g1", q: "엘리", creator: "u1", hashtag: "t" };
    const cleared = { ...search, ...HOME_FILTER_RESET };

    expect(hasHomeFilter(cleared)).toBe(false);
    expect(cleared.type).toBe("character");
    expect(cleared.sort).toBe("popular");
  });
});
