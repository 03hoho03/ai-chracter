import { describe, expect, it } from "vitest";

import { ApiErrorObject } from "@/shared/api/client";

import { getWithdrawalPayoutAction } from "./withdrawalPayoutAction";

const INFO = { maskedName: "홍*동", bankCode: "004", accountLast4: "1234" } as const;

function payout(
  overrides: Partial<NonNullable<Parameters<typeof getWithdrawalPayoutAction>[0]["payout"]>> = {},
): NonNullable<Parameters<typeof getWithdrawalPayoutAction>[0]["payout"]> {
  return {
    everApproved: true,
    balanceKrw: 5_000,
    minimumPayoutKrw: 10_000,
    payoutAvailable: true,
    payoutInfo: INFO,
    inProgressPayout: null,
    ...overrides,
  };
}

const UNAVAILABLE = new ApiErrorObject({ status: 503, message: "x", detail: { code: "CREATOR_PAYOUT_UNAVAILABLE" } });

describe("getWithdrawalPayoutAction", () => {
  it("최소액 미만 잔액은 이 자리에서 신청한다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout(), error: null, isBehindReconsent: false })).toEqual({ kind: "request", balanceKrw: 5_000 });
  });

  it("최소액보다 1원 적어도 이 자리에서 신청한다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout({ balanceKrw: 9_999 }), error: null, isBehindReconsent: false })).toEqual({
      kind: "request",
      balanceKrw: 9_999,
    });
  });

  // 최소액 이상은 일반 신청이라 정산 화면으로 보낸다.
  it("최소액과 같은 잔액부터는 정산 화면으로 보낸다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout({ balanceKrw: 10_000 }), error: null, isBehindReconsent: false })).toEqual({
      kind: "goToPayout",
      balanceKrw: 10_000,
    });
  });

  it("지급 정보가 없으면 정산 화면의 지급 정보로 보낸다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout({ payoutInfo: null }), error: null, isBehindReconsent: false })).toEqual({
      kind: "registerInfo",
      balanceKrw: 5_000,
    });
  });

  it("서버가 읽지 못하는 지급 정보도 다시 입력하러 보낸다", () => {
    const unreadable = payout({ payoutInfo: { ...INFO, maskedName: null } });
    expect(getWithdrawalPayoutAction({ payout: unreadable, error: null, isBehindReconsent: false })).toEqual({ kind: "registerInfo", balanceKrw: 5_000 });
  });

  it.each([0, -56])("잔액 %i 원이면 받을 것이 없다", (balanceKrw) => {
    expect(getWithdrawalPayoutAction({ payout: payout({ balanceKrw }), error: null, isBehindReconsent: false })).toEqual({ kind: "none" });
  });

  // 재동의 전에는 서버가 신청을 받지 않고(재동의 403) 모달이 앱을 가려 다른 화면으로 갈 수도 없다.
  it.each([5_000, 10_000])("재동의 모달 안에서는 잔액 %i 원도 동의 뒤 신청하라고만 말한다", (balanceKrw) => {
    expect(getWithdrawalPayoutAction({ payout: payout({ balanceKrw }), error: null, isBehindReconsent: true })).toEqual({
      kind: "afterReconsent",
      balanceKrw,
    });
  });

  it("재동의 모달 안이어도 받을 잔액이 없으면 아무것도 두지 않는다", () => {
    expect(
      getWithdrawalPayoutAction({ payout: payout({ balanceKrw: 0 }), error: null, isBehindReconsent: true }),
    ).toEqual({ kind: "none" });
  });

  it("처리 중인 지급이 있으면 그 사실만 말한다", () => {
    const inProgressPayout = { amountKrw: 12_000, requestedAt: "2026-10-05T00:00:00Z" };
    expect(getWithdrawalPayoutAction({ payout: payout({ inProgressPayout }), error: null, isBehindReconsent: false })).toEqual({ kind: "inProgress" });
  });

  it("승인된 적이 없으면 아무것도 두지 않는다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout({ everApproved: false }), error: null, isBehindReconsent: false })).toEqual({ kind: "none" });
  });

  it("서버가 지급을 받지 않으면 받을 수 없다고 말한다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout({ payoutAvailable: false }), error: null, isBehindReconsent: false })).toEqual({
      kind: "notOffered",
    });
  });

  it("서버가 새 신청을 받지 않아도 처리 중인 지급이 있으면 그 지급은 처리된다고 말한다", () => {
    const inProgressPayout = { amountKrw: 12_000, requestedAt: "2026-10-05T00:00:00Z" };
    expect(
      getWithdrawalPayoutAction({ payout: payout({ payoutAvailable: false, inProgressPayout }), error: null, isBehindReconsent: false }),
    ).toEqual({ kind: "inProgress" });
  });

  // 꺼진 동안은 신청이 503 이다 — 꺼지기 전 응답으로 버튼을 두면 누르자마자 실패한다.
  it("정산 꺼짐 503 이면 남아 있던 응답이 있어도 받을 수 없다고 말한다", () => {
    expect(getWithdrawalPayoutAction({ payout: payout(), error: UNAVAILABLE, isBehindReconsent: false })).toEqual({ kind: "notOffered" });
  });

  it("그 밖의 이유로 못 읽었으면 모른다", () => {
    const error = new ApiErrorObject({ status: 500, message: "x", detail: "x" });
    expect(getWithdrawalPayoutAction({ payout: undefined, error, isBehindReconsent: false })).toEqual({ kind: "unknown" });
  });

  it("읽는 중이면 아무것도 두지 않는다", () => {
    expect(getWithdrawalPayoutAction({ payout: undefined, error: null, isBehindReconsent: false })).toEqual({ kind: "none" });
  });
});
