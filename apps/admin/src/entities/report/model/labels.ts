import type { components } from "@ai-character-chat/api-types";

export const REPORT_REASON_LABELS: Record<components["schemas"]["ReportReasonCategory"], string> = {
  adult: "성인물",
  copyright: "저작권 침해",
  hate: "혐오/차별",
  spam: "스팸",
  other: "기타",
};

export const REPORT_STATUS_LABELS: Record<components["schemas"]["ReportStatus"], string> = {
  pending: "대기중",
  resolved: "처리완료",
  rejected: "반려",
};

export const CONTENT_TYPE_LABELS: Record<components["schemas"]["ContentType"], string> = {
  character: "캐릭터",
  story: "스토리",
};

export const MODERATION_STATUS_LABELS: Record<components["schemas"]["ModerationStatus"], string> = {
  normal: "정상",
  restricted: "이용제한",
  deleted: "삭제됨",
};
