import { describe, expect, it } from "vitest";

import { resolveStudioBodyView, resolveStudioEmptyResult } from "./studioBodyView";

describe("resolveStudioBodyView", () => {
  it("행이 있으면 목록", () => {
    expect(resolveStudioBodyView({ itemCount: 3, hasCondition: true, isShowingPlaceholder: false })).toBe("list");
  });

  it("조건이 없는데 0건이면 아직 만든 것이 없다", () => {
    expect(resolveStudioBodyView({ itemCount: 0, hasCondition: false, isShowingPlaceholder: false })).toBe(
      "nothingMade",
    );
  });

  it("조건이 걸린 0건은 빈 결과다", () => {
    expect(resolveStudioBodyView({ itemCount: 0, hasCondition: true, isShowingPlaceholder: false })).toBe(
      "emptyResult",
    );
  });

  it("검색어를 바꾼 뒤 자리표시로 0건을 보는 동안은 결론을 내지 않는다", () => {
    expect(resolveStudioBodyView({ itemCount: 0, hasCondition: true, isShowingPlaceholder: true })).toBe("awaiting");
  });
});

describe("resolveStudioEmptyResult", () => {
  it("필터만 걸리면 범위 이름으로 말하고 필터를 모두 푼다", () => {
    expect(resolveStudioEmptyResult({ q: undefined, filterLabel: "캐릭터 · 초안" })).toEqual({
      message: "‘캐릭터 · 초안’에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });

  it("검색어만 걸리면 찾은 말로 말하고 검색어만 지운다", () => {
    expect(resolveStudioEmptyResult({ q: "바다", filterLabel: undefined })).toEqual({
      message: "‘바다’로 찾은 작품이 없어요.",
      action: "clearQuery",
    });
    expect(resolveStudioEmptyResult({ q: "목욕탕", filterLabel: undefined }).message).toBe(
      "‘목욕탕’으로 찾은 작품이 없어요.",
    );
  });

  it("둘 다 걸리면 둘을 함께 적고 모두 푼다", () => {
    expect(resolveStudioEmptyResult({ q: "바다", filterLabel: "스토리" })).toEqual({
      message: "‘바다’ · ‘스토리’에 해당하는 작품이 없어요.",
      action: "resetAll",
    });
  });
});

describe("resolveStudioBodyView 의 묶음 화면", () => {
  it("조건 없는 0건이 홈에서는 아직 만든 것이 없음, 묶음에서는 아직 넣은 것이 없음이다", () => {
    const input = { itemCount: 0, hasCondition: false, isShowingPlaceholder: false };
    expect(resolveStudioBodyView({ ...input, isBundle: false })).toBe("nothingMade");
    expect(resolveStudioBodyView({ ...input, isBundle: true })).toBe("nothingAdded");
  });

  it("묶음에서도 조건이 걸린 0건은 빈 결과다", () => {
    expect(resolveStudioBodyView({ itemCount: 0, hasCondition: true, isShowingPlaceholder: false, isBundle: true })).toBe(
      "emptyResult",
    );
  });
});
