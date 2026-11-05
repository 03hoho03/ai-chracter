import { describe, expect, it } from "vitest";

import {
  CLOVER_HISTORY_SEARCH_SCHEMA,
  isCloverHistoryTab,
  resolveCloverHistoryTab,
} from "./cloverHistorySearch";

describe("CLOVER_HISTORY_SEARCH_SCHEMA", () => {
  it("파라미터가 없으면 undefined다 — 기본값(use)은 URL에 싣지 않는다", () => {
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({})).toEqual({});
  });

  it("기본값 use는 .exclude() 대상이라 그 자체도 부재로 접힌다", () => {
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({ tab: "use" })).toEqual({});
  });

  it("earn·expire는 그대로 통과한다", () => {
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({ tab: "earn" })).toEqual({ tab: "earn" });
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({ tab: "expire" })).toEqual({ tab: "expire" });
  });

  it("허용값 밖이면 그 축만 부재로 떨어뜨린다 — 던지면 라우터가 페이지를 통째로 죽인다", () => {
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({ tab: "charge" })).toEqual({});
    expect(CLOVER_HISTORY_SEARCH_SCHEMA.parse({ tab: 1 })).toEqual({});
  });
});

describe("resolveCloverHistoryTab", () => {
  it("파라미터가 없으면 기본값 use다", () => {
    expect(resolveCloverHistoryTab({})).toBe("use");
  });

  it("주어진 탭을 그대로 편다", () => {
    expect(resolveCloverHistoryTab({ tab: "expire" })).toBe("expire");
  });
});

describe("isCloverHistoryTab", () => {
  it("탭 3종만 통과시킨다 — Radix onValueChange가 흘리는 빈 문자열을 여기서 막는다", () => {
    expect(["use", "earn", "expire"].every(isCloverHistoryTab)).toBe(true);
    expect(isCloverHistoryTab("")).toBe(false);
    expect(isCloverHistoryTab("charge")).toBe(false);
  });
});
