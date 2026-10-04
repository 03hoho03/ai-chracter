import { describe, expect, it } from "vitest";

import { HOME_EMPTY_MESSAGE, toHomeListEndMessage, toHomeListStatus } from "./homeListStatus";

describe("toHomeListEndMessage", () => {
  it("조건이 없으면 그 유형 전체를 다 봤다고 말한다", () => {
    expect(toHomeListEndMessage("story", false)).toBe("모든 스토리를 봤어요");
    expect(toHomeListEndMessage("character", false)).toBe("모든 캐릭터를 봤어요");
  });

  it("조건이 걸려 있으면 '모든 스토리'라고 주장하지 않는다", () => {
    expect(toHomeListEndMessage("story", true)).toBe("조건에 맞는 스토리를 모두 봤어요");
    expect(toHomeListEndMessage("character", true)).toBe("조건에 맞는 캐릭터를 모두 봤어요");
  });
});

describe("toHomeListStatus", () => {
  const base = { type: "story" as const, isFiltered: false };

  it("첫 페이지를 기다리는 동안은 불러오는 중이다", () => {
    expect(toHomeListStatus({ ...base, isPending: true, isError: false, itemCount: 0, hasNextPage: false })).toBe(
      "작품을 불러오는 중이에요",
    );
  });

  it("보여 줄 것 없이 실패하면 실패를 말한다", () => {
    expect(toHomeListStatus({ ...base, isPending: false, isError: true, itemCount: 0, hasNextPage: false })).toBe(
      "목록을 불러오지 못했어요",
    );
  });

  it("0건이면 빈 상태 문장을 그대로 쓴다", () => {
    expect(toHomeListStatus({ ...base, isPending: false, isError: false, itemCount: 0, hasNextPage: false })).toBe(
      HOME_EMPTY_MESSAGE,
    );
  });

  it("남은 페이지가 있으면 총계를 주장하지 않는다", () => {
    const status = toHomeListStatus({ ...base, isPending: false, isError: false, itemCount: 20, hasNextPage: true });
    expect(status).toBe("작품 20개 표시 중");
  });

  it("끝까지 불러왔으면 건수와 끝 문구를 함께 말한다", () => {
    expect(toHomeListStatus({ ...base, isPending: false, isError: false, itemCount: 31, hasNextPage: false })).toBe(
      "작품 31개, 모든 스토리를 봤어요",
    );
    expect(
      toHomeListStatus({ type: "character", isFiltered: true, isPending: false, isError: false, itemCount: 2, hasNextPage: false }),
    ).toBe("작품 2개, 조건에 맞는 캐릭터를 모두 봤어요");
  });

  it("목록이 있는 채로 새로고침이 실패해도 건수를 말한다 — 실패는 화면의 경고 배너가 알린다", () => {
    expect(toHomeListStatus({ ...base, isPending: false, isError: true, itemCount: 20, hasNextPage: true })).toBe(
      "작품 20개 표시 중",
    );
  });
});
