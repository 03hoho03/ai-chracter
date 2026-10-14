import { describe, expect, it } from "vitest";

import { resolveMyWorksBodyView } from "./myWorksBodyView";

describe("resolveMyWorksBodyView", () => {
  it("검색도 없고 세 목록이 다 비었으면 만든 작품이 없는 화면이다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 0, visibleCount: 0, q: undefined, isShowingPlaceholder: false })).toBe(
      "nothingMade",
    );
  });

  it("0건 검색을 지운 직후 응답 전에는 이전 검색의 0건 자리표시로 '만든 작품 없음'을 말하지 않는다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 0, visibleCount: 0, q: undefined, isShowingPlaceholder: true })).toBe(
      "awaiting",
    );
  });

  it("검색어를 바꾸는 중 자리표시가 0건이면 이전 검색어의 빈 결과 문구를 새 검색어로 내보이지 않는다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 0, visibleCount: 0, q: "바다", isShowingPlaceholder: true })).toBe(
      "awaiting",
    );
    expect(resolveMyWorksBodyView({ itemCount: 3, visibleCount: 0, q: undefined, isShowingPlaceholder: true })).toBe(
      "awaiting",
    );
  });

  it("자리표시라도 보일 게 있으면 목록을 그대로 둔다 — 입력 중 목록이 사라지지 않게", () => {
    expect(resolveMyWorksBodyView({ itemCount: 2, visibleCount: 2, q: "바다", isShowingPlaceholder: true })).toBe("list");
  });

  it("응답이 온 뒤 검색어가 걸린 0건은 만든 게 없는 게 아니라 찾은 게 없는 것이다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 0, visibleCount: 0, q: "바다", isShowingPlaceholder: false })).toBe(
      "emptyResult",
    );
  });

  it("불러온 작품은 있는데 칩으로 거른 결과가 0건이면 빈 결과다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 4, visibleCount: 0, q: undefined, isShowingPlaceholder: false })).toBe(
      "emptyResult",
    );
  });

  it("보일 게 있으면 목록이다", () => {
    expect(resolveMyWorksBodyView({ itemCount: 4, visibleCount: 1, q: undefined, isShowingPlaceholder: false })).toBe(
      "list",
    );
  });
});
