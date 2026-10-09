import type { CreatorPayoutResponse } from "@/entities/creator-payout";

export type RequirementKey = "identity" | "adult" | "publishedWork";

/** `unknown` 은 아직 따질 수 없는 조건이다 — 나이는 본인인증한 생년월일로만 판정하므로, 인증 전에 "만 19세 미만"이라고
 * 말하면 거짓일 수 있다. */
export type RequirementState = "met" | "unmet" | "unknown";

export type Requirement = { key: RequirementKey; state: RequirementState };

/** 신청 영역에 무엇을 둘지.
 *
 * - `pending` — 검토 중이다. 다시 신청할 수 없다.
 * - `approved` — 적립 중이다.
 * - `open` — 신청할 수 있는 자리다. 앞선 신청이 반려·승인 취소로 끝났으면(`previous`) 그 사유를 함께 보이고, 다시 신청할
 *   수 있다. 정지 중이거나(`suspended`) 조건이 모자라면(`requirements`) 신청 버튼을 두지 않는다.
 *
 * 자격은 서버가 신청과 같은 판정으로 계산한 값이다. 여기서는 보여 줄 모양만 정한다. */
export type ApplicationView =
  | { kind: "pending"; appliedAt: string }
  | { kind: "approved"; decidedAt: string | null }
  | {
      kind: "open";
      previous: { status: "rejected" | "revoked"; reason: string; decidedAt: string | null } | null;
      suspended: boolean;
      requirements: Requirement[];
      canApply: boolean;
    };

function adultState(eligibility: CreatorPayoutResponse["eligibility"]): RequirementState {
  if (!eligibility.identityVerified) return "unknown";
  return eligibility.adult ? "met" : "unmet";
}

export function getApplicationView(payout: Pick<CreatorPayoutResponse, "application" | "eligibility">): ApplicationView {
  const { application, eligibility } = payout;
  if (application?.status === "pending") return { kind: "pending", appliedAt: application.appliedAt };
  if (application?.status === "approved") return { kind: "approved", decidedAt: application.decidedAt };

  const requirements: Requirement[] = [
    { key: "identity", state: eligibility.identityVerified ? "met" : "unmet" },
    { key: "adult", state: adultState(eligibility) },
    { key: "publishedWork", state: eligibility.hasPublishedWork ? "met" : "unmet" },
  ];
  return {
    kind: "open",
    previous: application
      ? { status: application.status, reason: application.decisionReason, decidedAt: application.decidedAt }
      : null,
    suspended: eligibility.suspended,
    requirements,
    canApply: !eligibility.suspended && requirements.every((requirement) => requirement.state === "met"),
  };
}
