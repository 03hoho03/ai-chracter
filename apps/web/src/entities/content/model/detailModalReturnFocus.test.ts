import { describe, expect, it } from "vitest";

import { pickDetailModalReturnFocus } from "./detailModalReturnFocus";

const card = { name: "card", isConnected: true };
const removedCard = { name: "removed-card", isConnected: false };
const results = { name: "results", isConnected: true };
const removedResults = { name: "removed-results", isConnected: false };

describe("pickDetailModalReturnFocus", () => {
  it("그냥 닫히면 모달을 연 요소로 돌려준다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: true, opener: card, fallback: results })).toBe(card);
  });

  it("탐색으로 닫혔으면 연 요소가 남아 있어도 돌려주지 않는다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: false, opener: card, fallback: results })).toBeNull();
  });

  it("연 요소가 사라졌으면 대체 착지점으로 보낸다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: true, opener: removedCard, fallback: results })).toBe(results);
  });

  it("연 요소를 모르면 대체 착지점으로 보낸다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: true, opener: null, fallback: results })).toBe(results);
  });

  it("연 요소도 대체 착지점도 사라졌으면 아무 데도 안 보낸다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: true, opener: removedCard, fallback: removedResults })).toBeNull();
  });

  it("대체 착지점이 없는 화면에서 연 요소가 사라졌으면 아무 데도 안 보낸다", () => {
    expect(pickDetailModalReturnFocus({ isPlainClose: true, opener: removedCard, fallback: null })).toBeNull();
  });
});
