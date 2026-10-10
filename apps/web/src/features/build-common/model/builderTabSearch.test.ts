import { describe, expect, it } from "vitest";

import { tabFromSearch, tabToSearch } from "./builderTabSearch";

const TABS = [{ id: "profile" }, { id: "intro" }, { id: "detail" }] as const;

describe("tabFromSearch", () => {
  it("이 빌더의 탭 id 면 그 탭을 연다", () => {
    expect(tabFromSearch("detail", TABS)).toBe("detail");
  });

  it.each([
    ["값이 없다", undefined],
    ["다른 빌더의 탭 id 다", "mediaBook"],
    ["손으로 고친 값이다", "DETAIL"],
    ["빈 문자열이다", ""],
  ])("%s면 기본 탭(첫 탭)이다", (_name, raw) => {
    expect(tabFromSearch(raw, TABS)).toBe("profile");
  });
});

describe("tabToSearch", () => {
  it("기본 탭은 파라미터를 지운다", () => {
    expect(tabToSearch("profile", TABS)).toBeUndefined();
  });

  it("다른 탭은 그 id 를 적는다", () => {
    expect(tabToSearch("intro", TABS)).toBe("intro");
  });

  it("적은 값을 다시 읽으면 같은 탭이다", () => {
    for (const { id } of TABS) {
      expect(tabFromSearch(tabToSearch(id, TABS), TABS)).toBe(id);
    }
  });
});
