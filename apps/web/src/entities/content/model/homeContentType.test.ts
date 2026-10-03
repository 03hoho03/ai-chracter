import { describe, expect, it } from "vitest";

import { resolveHomeContentType, toHomeTypeParam, toHomeTypeSwitchSearch } from "./homeContentType";

describe("toHomeTypeParam", () => {
  it("스토리는 URL에 싣지 않는다 — 파라미터의 부재가 곧 스토리다", () => {
    expect(toHomeTypeParam("story")).toBeUndefined();
  });

  it("캐릭터는 그대로 싣는다", () => {
    expect(toHomeTypeParam("character")).toBe("character");
  });
});

describe("resolveHomeContentType", () => {
  it("파라미터가 없으면 스토리다", () => {
    expect(resolveHomeContentType(undefined)).toBe("story");
  });

  it("파라미터가 있으면 그 유형이다", () => {
    expect(resolveHomeContentType("character")).toBe("character");
  });

  it("toHomeTypeParam 과 왕복하면 원래 유형으로 돌아온다", () => {
    expect(resolveHomeContentType(toHomeTypeParam("story"))).toBe("story");
    expect(resolveHomeContentType(toHomeTypeParam("character"))).toBe("character");
  });
});

describe("toHomeTypeSwitchSearch", () => {
  it("정렬만 들고 가고 나머지 축은 남기지 않는다", () => {
    const next = toHomeTypeSwitchSearch("character", "popular");

    expect(next).toEqual({ type: "character", sort: "popular" });
    // 키 자체가 없어야 한다 — 값이 undefined 인 키도 남기지 않는다.
    expect(Object.keys(next).sort()).toEqual(["sort", "type"]);
  });

  it("스토리로 전환하면 type 을 싣지 않는다", () => {
    expect(toHomeTypeSwitchSearch("story", "popular")).toEqual({ sort: "popular" });
    expect(Object.keys(toHomeTypeSwitchSearch("story", "popular"))).toEqual(["sort"]);
  });

  it("정렬이 기본값(부재)이면 정렬도 싣지 않는다", () => {
    expect(toHomeTypeSwitchSearch("story", undefined)).toEqual({});
    expect(Object.keys(toHomeTypeSwitchSearch("character", undefined))).toEqual(["type"]);
  });
});
