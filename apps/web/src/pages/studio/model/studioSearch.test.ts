import { describe, expect, it } from "vitest";

import { MY_WORKS_QUERY_MAX_LENGTH } from "@/entities/work";

import { resolveStudioScope, resolveStudioSearch, studioSearchSchema, UNREADABLE_BUNDLE } from "./studioSearch";

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

const BUNDLE_ID = "0b7a5a2e-7c1d-4f3e-9a6b-2d8c1e4f5a60";

describe("studioSearchSchema 의 묶음", () => {
  it("id 모양이면 그대로 받는다 — RFC 변형 비트가 아닌 id 도 서버가 받으므로 받는다", () => {
    expect(studioSearchSchema.parse({ bundle: BUNDLE_ID }).bundle).toBe(BUNDLE_ID);
    const nonRfc = "0b7a5a2e-7c1d-0f3e-0a6b-2d8c1e4f5a60";
    expect(studioSearchSchema.parse({ bundle: nonRfc }).bundle).toBe(nonRfc);
  });

  it("없으면 부재, 모양이 틀리면 읽을 수 없는 묶음으로 남긴다 — 홈으로 조용히 바뀌지 않게", () => {
    expect(studioSearchSchema.parse({}).bundle).toBeUndefined();
    expect(studioSearchSchema.parse({ bundle: "abc" }).bundle).toBe(UNREADABLE_BUNDLE);
    expect(studioSearchSchema.parse({ bundle: 123 }).bundle).toBe(UNREADABLE_BUNDLE);
  });
});

describe("resolveStudioScope", () => {
  it("묶음이 없으면 홈, 있으면 그 묶음, 모양이 틀리면 읽을 수 없는 묶음", () => {
    expect(resolveStudioScope({})).toEqual({ kind: "home" });
    expect(resolveStudioScope({ bundle: BUNDLE_ID })).toEqual({ kind: "bundle", bundleId: BUNDLE_ID });
    expect(resolveStudioScope({ bundle: UNREADABLE_BUNDLE })).toEqual({ kind: "unreadableBundle" });
  });
});

describe("resolveStudioSearch 의 묶음", () => {
  it("묶음 화면은 묶음 id 를 싣고 상태를 전체로 접는다 — 상태 셀렉트가 없어 걸린 상태를 풀 방법이 없다", () => {
    expect(resolveStudioSearch({ bundle: BUNDLE_ID, type: "story", status: "draft", q: "밤" }, true)).toEqual({
      type: "story",
      status: "all",
      bundleId: BUNDLE_ID,
      q: "밤",
    });
  });

  it("홈은 상태를 그대로 두고 묶음 id 를 싣지 않는다", () => {
    const params = resolveStudioSearch({ type: "story", status: "draft" }, true);
    expect(params.status).toBe("draft");
    expect(params.bundleId).toBeUndefined();
  });

  it("읽을 수 없는 묶음은 서버로 보낼 묶음 id 가 없다", () => {
    expect(resolveStudioSearch({ bundle: UNREADABLE_BUNDLE }, true).bundleId).toBeUndefined();
  });
});
