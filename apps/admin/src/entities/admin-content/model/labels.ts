import type { components } from "@ai-character-chat/api-types";

export type ContentType = components["schemas"]["ContentType"];
export type ContentVisibility = components["schemas"]["ContentVisibility"];
export type ModerationStatus = components["schemas"]["ModerationStatus"];

export const CONTENT_TYPE_LABELS: Record<ContentType, string> = {
  character: "캐릭터",
  story: "스토리",
};

export const CONTENT_VISIBILITY_LABELS: Record<ContentVisibility, string> = {
  public: "공개",
  link: "링크공개",
  private: "비공개",
};

export const MODERATION_STATUS_LABELS: Record<ModerationStatus, string> = {
  normal: "정상",
  restricted: "이용제한",
  deleted: "삭제됨",
};

export function isContentType(value: string): value is ContentType {
  return value in CONTENT_TYPE_LABELS;
}

export function isContentVisibility(value: string): value is ContentVisibility {
  return value in CONTENT_VISIBILITY_LABELS;
}

export function isModerationStatus(value: string): value is ModerationStatus {
  return value in MODERATION_STATUS_LABELS;
}

/** 서버 스키마에 멤버가 늘면 각 `*_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로
 * 또 적으면 그 강제가 목록에는 걸리지 않아 새 멤버가 라우트 검증과 필터에서 조용히 빠진다.
 * 그래서 셋 다 키에서 도출한다(`entities/inquiry/model/labels.ts` 동형). */
export const CONTENT_TYPE_VALUES = Object.keys(CONTENT_TYPE_LABELS).filter(isContentType);
export const CONTENT_VISIBILITY_VALUES = Object.keys(CONTENT_VISIBILITY_LABELS).filter(isContentVisibility);
export const MODERATION_STATUS_VALUES = Object.keys(MODERATION_STATUS_LABELS).filter(isModerationStatus);

export const CONTENT_TYPE_OPTIONS = CONTENT_TYPE_VALUES.map((value) => ({
  value,
  label: CONTENT_TYPE_LABELS[value],
}));

export const CONTENT_VISIBILITY_OPTIONS = CONTENT_VISIBILITY_VALUES.map((value) => ({
  value,
  label: CONTENT_VISIBILITY_LABELS[value],
}));

export const MODERATION_STATUS_OPTIONS = MODERATION_STATUS_VALUES.map((value) => ({
  value,
  label: MODERATION_STATUS_LABELS[value],
}));
