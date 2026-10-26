import { describe, expect, it } from "vitest";

import type { CloverLedgerItem } from "@/entities/clover";

import { hasLedgerEntries, toLedgerRowView } from "./ledgerRow";

function item(patch: Partial<CloverLedgerItem>): CloverLedgerItem {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    amount: -30,
    balanceAfter: 1200,
    kind: "chat_spend",
    category: "use",
    createdAt: "2026-10-01T00:00:00Z",
    legacyUnit: false,
    ...patch,
  };
}

describe("toLedgerRowView", () => {
  it("거래 행은 라벨과 부호 붙은 금액이다", () => {
    expect(toLedgerRowView(item({}))).toEqual({ kind: "entry", label: "채팅 사용", amount: "-30", isLegacyUnit: false });
  });

  // 옛 단위로 적힌 숫자는 지금 잔액과 같은 단위로 더하고 뺄 수 없다 — 그렇다고 표시해야 검산하다 헷갈리지 않는다.
  it("전환 전 단위로 적힌 행에는 이전 단위 표시를 붙인다", () => {
    expect(toLedgerRowView(item({ legacyUnit: true }))).toMatchObject({ kind: "entry", isLegacyUnit: true });
  });

  // 단위 전환은 거래가 아니라 경계다 — 금액 행으로 그리면 잔액이 그만큼 늘거나 준 거래로 읽힌다. 문구는 원장 종류 이름이
  // 아니라 무슨 일이 있었는지를 사용자 말로 한다.
  it.each([
    ["unit_conversion", "클로버 단위가 1원 단위로 바뀌었어요"],
    ["unit_conversion_revert", "클로버 단위가 이전 단위로 돌아갔어요"],
  ])("단위 전환 기록(%s)은 경계 줄이다", (kind, title) => {
    expect(toLedgerRowView(item({ kind, category: "conversion", amount: 2400, balanceAfter: 3600 }))).toEqual({
      kind: "boundary",
      title,
      balance: "이때 잔액 클로버 3,600개",
    });
  });

  it("모르는 전환 종류도 경계 줄로 그리고 바뀌었다고만 말한다", () => {
    expect(toLedgerRowView(item({ kind: "unit_future", category: "conversion" }))).toMatchObject({
      kind: "boundary",
      title: "클로버 단위가 바뀌었어요",
    });
  });
});

describe("hasLedgerEntries", () => {
  // 경계 줄은 거래가 아니다 — 경계 줄만 있는 탭에서 빈 안내를 빼면 그 탭에 거래가 있는 것처럼 읽힌다.
  it("단위 전환 경계 줄만 있으면 거래가 없다", () => {
    expect(hasLedgerEntries([item({ kind: "unit_conversion", category: "conversion" })])).toBe(false);
  });

  it("거래 행이 하나라도 있으면 거래가 있다", () => {
    expect(hasLedgerEntries([item({ kind: "unit_conversion", category: "conversion" }), item({})])).toBe(true);
  });
});
