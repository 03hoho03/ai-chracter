import { describe, expect, it } from "vitest";

import { getBalancePayoutNote, getPayoutSections } from "./payoutSections";

const IN_PROGRESS = { amountKrw: 12_000, requestedAt: "2026-10-05T00:00:00Z" };

describe("getPayoutSections", () => {
  it("서버가 지급을 받으면 신청·지급 정보·지급 내역을 모두 보인다", () => {
    expect(getPayoutSections({ everApproved: true, payoutAvailable: true, inProgressPayout: null })).toEqual({
      request: true,
      payoutInfo: true,
      payouts: true,
    });
  });

  it("서버가 새 신청을 받지 않아도 지급 내역은 보이고, 신청과 지급 정보는 감춘다", () => {
    expect(getPayoutSections({ everApproved: true, payoutAvailable: false, inProgressPayout: IN_PROGRESS })).toEqual({
      request: false,
      payoutInfo: false,
      payouts: true,
    });
  });

  it("승인된 적이 없으면 아무것도 보이지 않는다", () => {
    expect(getPayoutSections({ everApproved: false, payoutAvailable: true, inProgressPayout: null })).toEqual({
      request: false,
      payoutInfo: false,
      payouts: false,
    });
  });
});

describe("getBalancePayoutNote", () => {
  it("서버가 새 신청을 받지 않아도 처리 중인 지급이 있으면 준비 중이라고 하지 않는다", () => {
    const note = getBalancePayoutNote({ everApproved: true, payoutAvailable: false, inProgressPayout: IN_PROGRESS });
    expect(note).not.toContain("준비 중");
    expect(note).toContain("신청한 지급은 처리하고 있어요");
  });

  it("처리 중인 지급 없이 서버가 신청을 받지 않으면 준비 중이라고 말한다", () => {
    expect(getBalancePayoutNote({ everApproved: true, payoutAvailable: false, inProgressPayout: null })).toContain("준비 중");
  });
});
