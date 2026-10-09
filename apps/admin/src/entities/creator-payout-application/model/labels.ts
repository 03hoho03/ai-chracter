import type { CreatorPayoutApplicationStatus } from "../api/keys";

export const CREATOR_PAYOUT_APPLICATION_STATUS_LABELS: Record<CreatorPayoutApplicationStatus, string> = {
  pending: "대기중",
  approved: "승인",
  rejected: "거절",
  revoked: "승인 취소",
};
