import type { components } from "@ai-character-chat/api-types";

export const CONTENT_TYPE_LABELS: Record<components["schemas"]["ContentType"], string> = {
  character: "캐릭터",
  story: "스토리",
};

export const CONTENT_VISIBILITY_LABELS: Record<components["schemas"]["ContentVisibility"], string> = {
  public: "공개",
  link: "링크공개",
  private: "비공개",
};

export const MODERATION_STATUS_LABELS: Record<components["schemas"]["ModerationStatus"], string> = {
  normal: "정상",
  restricted: "이용제한",
  deleted: "삭제됨",
};

export const REASON_CATEGORY_LABELS: Record<components["schemas"]["ReportReasonCategory"], string> = {
  adult: "성인물",
  copyright: "저작권 침해",
  hate: "혐오/차별",
  spam: "스팸",
  other: "기타",
};
