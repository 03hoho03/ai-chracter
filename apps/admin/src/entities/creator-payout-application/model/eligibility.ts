import type { components } from "@ai-character-chat/api-types";

type Eligibility = components["schemas"]["AdminCreatorPayoutEligibility"];

/** 서버가 신청·승인을 막는 이유. 승인 409 `CREATOR_PAYOUT_NOT_ELIGIBLE` 의 `reason` 값과 같은 말이다. */
const CREATOR_PAYOUT_BLOCK_REASONS = [
  "withdrawn",
  "suspended",
  "identity_required",
  "age_restricted",
  "no_published_work",
] as const;

export type CreatorPayoutBlockReason = (typeof CREATOR_PAYOUT_BLOCK_REASONS)[number];

export const CREATOR_PAYOUT_BLOCK_REASON_LABELS: Record<CreatorPayoutBlockReason, string> = {
  withdrawn: "탈퇴한 회원",
  suspended: "이용 정지 중",
  identity_required: "본인인증 안 함",
  age_restricted: "만 19세 미만",
  no_published_work: "발행 작품 없음",
};

/** 승인을 막는 첫 이유. 서버 판정과 같은 순서로 본다(탈퇴 → 정지 → 인증 → 나이 → 발행 작품). 막히지 않으면 `null`. */
export function getCreatorPayoutBlockReason(eligibility: Eligibility): CreatorPayoutBlockReason | null {
  if (eligibility.withdrawn) return "withdrawn";
  if (eligibility.suspended) return "suspended";
  if (!eligibility.identityVerified) return "identity_required";
  if (!eligibility.adult) return "age_restricted";
  if (eligibility.publishedCount === 0) return "no_published_work";
  return null;
}

/** 409 `reason` 은 OpenAPI 에 실리지 않아 모르는 값으로 온다 — 아는 값일 때만 좁힌다. */
export function toCreatorPayoutBlockReason(value: unknown): CreatorPayoutBlockReason | null {
  return CREATOR_PAYOUT_BLOCK_REASONS.find((reason) => reason === value) ?? null;
}
