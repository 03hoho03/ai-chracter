import type { components } from "@ai-character-chat/api-types";

export const APPEAL_TARGET_KIND_LABELS: Record<components["schemas"]["AppealTargetKind"], string> = {
  "publish-rejection": "발행 거부",
  "moderation-action": "조치 통지",
};

export const APPEAL_STATUS_LABELS: Record<components["schemas"]["AppealStatus"], string> = {
  pending: "대기중",
  resolved: "처리완료",
};

export const APPEAL_VERDICT_LABELS: Record<components["schemas"]["AppealVerdict"], string> = {
  accepted: "인용",
  rejected: "기각",
};
