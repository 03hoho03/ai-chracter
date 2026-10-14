import { describe, expect, it } from "vitest";

import {
  isMyWorkTypeFilter,
  isMyWorksSort,
  MY_WORKS_QUERY_MAX_LENGTH,
  myWorksSearchSchema,
  normalizeMyWorksQuery,
  resolveMyWorksSearch,
} from "./myWorksSearch";

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

describe("myWorksSearchSchema의 검색어", () => {
  it("앞뒤 공백을 걷어 그대로 쓴다", () => {
    expect(myWorksSearchSchema.parse({ q: "  목욕탕 " })).toEqual({ q: "목욕탕" });
  });

  it("비거나 공백뿐이면 부재다 — 빈 검색은 검색하지 않은 것과 같다", () => {
    expect(myWorksSearchSchema.parse({ q: "" }).q).toBeUndefined();
    expect(myWorksSearchSchema.parse({ q: "   " }).q).toBeUndefined();
  });

  it("손으로 고친 URL의 긴 검색어는 상한까지 잘린다 — 그대로 보내면 서버가 422로 거절한다", () => {
    expect(myWorksSearchSchema.parse({ q: "가".repeat(101) }).q).toBe("가".repeat(MY_WORKS_QUERY_MAX_LENGTH));
  });

  it("문자열이 아닌 값은 그 축만 부재로 떨어뜨린다 — 라우터는 `?q=1`을 숫자로 넘긴다", () => {
    expect(myWorksSearchSchema.parse({ q: 1, type: "story" })).toEqual({ type: "story" });
    expect(myWorksSearchSchema.parse({ q: { a: 1 } })).toEqual({});
  });
});

describe("normalizeMyWorksQuery", () => {
  it("상한 이하의 검색어는 손대지 않는다(가운데 공백·`%` 포함)", () => {
    expect(normalizeMyWorksQuery("100% 순정")).toBe("100% 순정");
    expect(normalizeMyWorksQuery("가".repeat(MY_WORKS_QUERY_MAX_LENGTH))).toBe("가".repeat(MY_WORKS_QUERY_MAX_LENGTH));
  });

  it("자른 끝에 남은 공백도 걷는다", () => {
    expect(normalizeMyWorksQuery(`${"가".repeat(99)} 나`)).toBe("가".repeat(99));
  });

  it("공백을 먼저 걷고 나서 센다 — 앞 공백 때문에 실제 글자가 잘리면 안 된다", () => {
    expect(normalizeMyWorksQuery(`   ${"가".repeat(MY_WORKS_QUERY_MAX_LENGTH)}`)).toBe(
      "가".repeat(MY_WORKS_QUERY_MAX_LENGTH),
    );
  });

  it("코드 포인트로 센다 — 이모지를 반으로 가르면 인코딩할 수 없는 문자열이 된다", () => {
    const query = normalizeMyWorksQuery(`${"가".repeat(99)}🌙🌙`);
    expect(query).toBe(`${"가".repeat(99)}🌙`);
    expect(() => encodeURIComponent(query ?? "")).not.toThrow();
    // 서버 상한은 파이썬 `len`이다 — 이모지 100개는 UTF-16으로 200단위지만 그대로 통과해야 한다.
    expect(normalizeMyWorksQuery("🌙".repeat(MY_WORKS_QUERY_MAX_LENGTH))).toBe("🌙".repeat(MY_WORKS_QUERY_MAX_LENGTH));
  });
});

describe("resolveMyWorksSearch", () => {
  it("파라미터가 없으면 세 축 모두 기본값이다 — 기본값 규칙이 여기 하나뿐이다", () => {
    expect(resolveMyWorksSearch({})).toEqual({ type: "all", visibility: "all", sort: "latest", q: undefined });
  });

  it("파라미터를 그대로 편다", () => {
    expect(resolveMyWorksSearch({ type: "story", visibility: "private", sort: "latest" })).toEqual({
      type: "story",
      visibility: "private",
      sort: "latest",
    });
  });

  it("검색어는 칩 축과 독립으로 남는다 — 미등록에서도 지워지지 않는다", () => {
    expect(resolveMyWorksSearch({ type: "unpublished", q: "초안" }).q).toBe("초안");
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
