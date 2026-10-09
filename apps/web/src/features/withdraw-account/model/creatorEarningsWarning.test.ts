import { describe, expect, it } from "vitest";

import type { CreatorPayoutApplication } from "@/entities/creator-payout";
import { ApiErrorObject } from "@/shared/api/client";

import { getCreatorEarningsWarning } from "./creatorEarningsWarning";

const NOW = new Date("2026-10-20T00:00:00Z");

function application(status: CreatorPayoutApplication["status"], revokedAt: string | null = null): CreatorPayoutApplication {
  return { status, appliedAt: "2026-09-01T00:00:00Z", decidedAt: "2026-09-02T00:00:00Z", decisionReason: "", revokedAt };
}

function payout(overrides: { everApproved?: boolean; balanceKrw?: number; application?: CreatorPayoutApplication | null } = {}) {
  return { everApproved: true, balanceKrw: 0, application: application("approved"), ...overrides };
}

const UNAVAILABLE = new ApiErrorObject({ status: 503, message: "x", detail: { code: "CREATOR_PAYOUT_UNAVAILABLE" } });

describe("getCreatorEarningsWarning", () => {
  it("확정 잔액이 있으면 그 금액으로 경고한다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: payout({ balanceKrw: 293 }), error: null, now: NOW });
    expect(warning).toEqual({ kind: "confirmed", balanceKrw: 293 });
  });

  it("잔액이 0 이어도 승인 중이면 미확정 적립만 있다면 사라진다고 경고한다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: payout(), error: null, now: NOW });
    expect(warning).toEqual({ kind: "unconfirmed" });
  });

  it("음수 잔액은 확정 적립금으로 적지 않고 미확정 적립만 말한다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: payout({ balanceKrw: -56 }), error: null, now: NOW });
    expect(warning).toEqual({ kind: "unconfirmed" });
  });

  it("승인된 적이 없으면 경고하지 않는다", () => {
    const warning = getCreatorEarningsWarning({
      isPayoutEnabled: true,
      payout: payout({ everApproved: false, application: application("pending") }),
      error: null,
      now: NOW,
    });
    expect(warning).toEqual({ kind: "none" });
  });

  it("정산이 꺼져 있으면 잔액이 있어도 경고하지 않는다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: false, payout: payout({ balanceKrw: 293 }), error: null, now: NOW });
    expect(warning).toEqual({ kind: "none" });
  });

  // 꺼져도 탈퇴하면 적립은 사라진다. 꺼진 동안은 잔액을 읽을 수 없어 금액 없이 조건으로만 말한다.
  it("정산 꺼짐 503 이면 금액 없는 조건부 경고다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: undefined, error: UNAVAILABLE, now: NOW });
    expect(warning).toEqual({ kind: "unavailable" });
  });

  // 앞서 받은 응답은 꺼지기 전 값이라 그사이 확정이 돌았으면 틀린다 — 그 금액을 적지 않는다.
  it("정산 꺼짐 503 이면 남아 있던 응답이 있어도 금액을 적지 않는다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: payout({ balanceKrw: 293 }), error: UNAVAILABLE, now: NOW });
    expect(warning).toEqual({ kind: "unavailable" });
  });

  it("그 밖의 이유로 못 읽었으면 숫자 없는 경고다", () => {
    const warning = getCreatorEarningsWarning({ isPayoutEnabled: true, payout: undefined, error: new ApiErrorObject({ status: 500, message: "x", detail: "x" }), now: NOW });
    expect(warning).toEqual({ kind: "unknown" });
  });

  it("읽는 중이면 아직 경고하지 않는다", () => {
    expect(getCreatorEarningsWarning({ isPayoutEnabled: true, payout: undefined, error: null, now: NOW })).toEqual({ kind: "none" });
  });

  describe("승인 취소 뒤 잔액이 0", () => {
    // 10월 중 취소 → 10월 적립은 11-03 00:00 KST(= 11-02 15:00 UTC)에 확정할 수 있게 된다.
    const revoked = payout({ application: application("revoked", "2026-10-10T03:00:00Z") });

    it("취소한 달이 아직 확정되기 전이면 경고한다", () => {
      const warning = getCreatorEarningsWarning({
        isPayoutEnabled: true,
        payout: revoked,
        error: null,
        now: new Date("2026-11-02T14:59:59Z"),
      });
      expect(warning).toEqual({ kind: "unconfirmed" });
    });

    it("취소한 달이 확정된 뒤면 잃을 것이 없어 경고하지 않는다", () => {
      const warning = getCreatorEarningsWarning({
        isPayoutEnabled: true,
        payout: revoked,
        error: null,
        now: new Date("2026-11-02T15:00:00Z"),
      });
      expect(warning).toEqual({ kind: "none" });
    });

    // 한국 시각으로는 11월 1일 새벽이라 확정 시점은 12월 3일이다.
    it("달은 한국 시각으로 가른다", () => {
      const warning = getCreatorEarningsWarning({
        isPayoutEnabled: true,
        payout: payout({ application: application("revoked", "2026-10-31T16:00:00Z") }),
        error: null,
        now: new Date("2026-11-20T00:00:00Z"),
      });
      expect(warning).toEqual({ kind: "unconfirmed" });
    });
  });

  // 가장 최근 신청만 오므로 앞선 승인 취소가 언제였는지 모른다.
  it.each(["pending", "rejected"] as const)("취소 뒤 다시 신청해 %s 이면 미확정 적립이 있을 수 있다고 본다", (status) => {
    const warning = getCreatorEarningsWarning({
      isPayoutEnabled: true,
      payout: payout({ application: application(status) }),
      error: null,
      now: NOW,
    });
    expect(warning).toEqual({ kind: "unconfirmed" });
  });
});
