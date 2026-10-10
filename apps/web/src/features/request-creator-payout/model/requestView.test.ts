import { describe, expect, it } from "vitest";

import { getRequestView, type RequestViewInput } from "./requestView";

const INFO = { maskedName: "홍*동", bankCode: "004", accountLast4: "1234" } as const;

function payout(overrides: Partial<RequestViewInput> = {}): RequestViewInput {
  return { balanceKrw: 25_000, minimumPayoutKrw: 10_000, payoutInfo: INFO, inProgressPayout: null, ...overrides };
}

describe("getRequestView", () => {
  it("잔액이 최소액 이상이고 지급 정보가 있으면 잔액 전액을 신청할 수 있다", () => {
    expect(getRequestView(payout())).toEqual({ kind: "ready", amountKrw: 25_000 });
  });

  // 최소액과 같은 잔액은 서버가 받는다(미만만 거절).
  it("잔액이 최소액과 같으면 신청할 수 있다", () => {
    expect(getRequestView(payout({ balanceKrw: 10_000 }))).toEqual({ kind: "ready", amountKrw: 10_000 });
  });

  it("최소액보다 1원 적으면 최소액을 말한다", () => {
    expect(getRequestView(payout({ balanceKrw: 9_999 }))).toEqual({ kind: "belowMinimum", minimumKrw: 10_000 });
  });

  it.each([0, -56])("잔액 %i 원은 신청할 것이 없다", (balanceKrw) => {
    expect(getRequestView(payout({ balanceKrw }))).toEqual({ kind: "nothingToPay" });
  });

  // 처리 중인 건이 있으면 서버가 새 신청을 거절한다 — 그사이 잔액이 다시 쌓여도 버튼을 두지 않는다.
  it("처리 중인 지급이 있으면 잔액과 무관하게 처리 중이다", () => {
    const inProgressPayout = { amountKrw: 30_000, requestedAt: "2026-10-05T00:00:00Z" };
    expect(getRequestView(payout({ inProgressPayout }))).toEqual({ kind: "inProgress", ...inProgressPayout });
  });

  it("지급 정보가 없으면 등록부터 하라고 한다", () => {
    expect(getRequestView(payout({ payoutInfo: null }))).toEqual({ kind: "infoRequired" });
  });

  // 서버가 실명을 복호화하지 못하면 운영자도 원문을 못 읽어 이체할 수 없다.
  it("지급 정보를 읽을 수 없으면 신청 대신 다시 입력하라고 한다", () => {
    expect(getRequestView(payout({ payoutInfo: { ...INFO, maskedName: null } }))).toEqual({ kind: "infoUnreadable" });
  });

  // 최소액 미만이면 지급 정보가 없어도 먼저 최소액을 말한다 — 등록해도 아직 신청할 수 없다.
  it("최소액 미만이면 지급 정보가 없어도 최소액을 말한다", () => {
    expect(getRequestView(payout({ balanceKrw: 500, payoutInfo: null }))).toEqual({
      kind: "belowMinimum",
      minimumKrw: 10_000,
    });
  });
});
