import { describe, expect, it } from "vitest";

import type { CreatorPayoutApplication, CreatorPayoutEligibility } from "@/entities/creator-payout";

import { getApplicationView } from "./applicationView";

const ELIGIBLE: CreatorPayoutEligibility = { identityVerified: true, adult: true, hasPublishedWork: true, suspended: false };

function application(status: CreatorPayoutApplication["status"]): CreatorPayoutApplication {
  return {
    status,
    appliedAt: "2026-10-01T00:00:00Z",
    decidedAt: "2026-10-02T00:00:00Z",
    decisionReason: "사유",
    revokedAt: status === "revoked" ? "2026-10-05T00:00:00Z" : null,
  };
}

describe("getApplicationView", () => {
  it("신청한 적이 없고 조건을 다 갖췄으면 신청할 수 있다", () => {
    const view = getApplicationView({ application: null, eligibility: ELIGIBLE });
    expect(view).toMatchObject({ kind: "open", previous: null, canApply: true });
  });

  it("대기 중이면 검토 중이다", () => {
    expect(getApplicationView({ application: application("pending"), eligibility: ELIGIBLE }).kind).toBe("pending");
  });

  it("승인됐으면 승인이다", () => {
    expect(getApplicationView({ application: application("approved"), eligibility: ELIGIBLE }).kind).toBe("approved");
  });

  it.each(["rejected", "revoked"] as const)("%s 로 끝난 신청은 사유를 보이고 다시 신청할 수 있다", (status) => {
    const view = getApplicationView({ application: application(status), eligibility: ELIGIBLE });
    expect(view).toMatchObject({ kind: "open", previous: { status, reason: "사유" }, canApply: true });
  });

  it("반려된 신청은 반려한 날을 끝난 날로 보인다", () => {
    const view = getApplicationView({ application: application("rejected"), eligibility: ELIGIBLE });
    expect(view.kind === "open" && view.previous?.endedAt).toBe("2026-10-02T00:00:00Z");
  });

  // 승인 취소된 신청의 decidedAt 은 승인한 날이다 — 그것을 보이면 승인일이 취소일 행세를 한다.
  it("승인 취소된 신청은 승인한 날이 아니라 취소한 날을 끝난 날로 보인다", () => {
    const view = getApplicationView({ application: application("revoked"), eligibility: ELIGIBLE });
    expect(view.kind === "open" && view.previous?.endedAt).toBe("2026-10-05T00:00:00Z");
  });

  // 나이는 인증한 생년월일로만 판정한다 — 인증 전에 "만 19세 미만"이라고 하면 거짓일 수 있다.
  it("인증 전에는 나이 조건을 아직 모르는 것으로 둔다", () => {
    const view = getApplicationView({
      application: null,
      eligibility: { ...ELIGIBLE, identityVerified: false, adult: false },
    });
    expect(view.kind === "open" && view.requirements).toEqual([
      { key: "identity", state: "unmet" },
      { key: "adult", state: "unknown" },
      { key: "publishedWork", state: "met" },
    ]);
    expect(view.kind === "open" && view.canApply).toBe(false);
  });

  it("인증했는데 만 19세 미만이면 나이 조건이 모자라다", () => {
    const view = getApplicationView({ application: null, eligibility: { ...ELIGIBLE, adult: false } });
    expect(view.kind === "open" && view.requirements.find((requirement) => requirement.key === "adult")?.state).toBe("unmet");
    expect(view.kind === "open" && view.canApply).toBe(false);
  });

  it("발행한 작품이 없으면 신청할 수 없다", () => {
    const view = getApplicationView({ application: null, eligibility: { ...ELIGIBLE, hasPublishedWork: false } });
    expect(view.kind === "open" && view.canApply).toBe(false);
  });

  it("정지 중이면 조건을 다 갖춰도 신청할 수 없다", () => {
    const view = getApplicationView({ application: null, eligibility: { ...ELIGIBLE, suspended: true } });
    expect(view).toMatchObject({ kind: "open", suspended: true, canApply: false });
  });
});
