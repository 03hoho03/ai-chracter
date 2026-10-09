import type { components } from "@ai-character-chat/api-types";

type AdminNovelListItem = components["schemas"]["AdminNovelListItem"];
type AdminNovelScreeningItem = components["schemas"]["AdminNovelScreeningItem"];
type AdminNovelCommentItem = components["schemas"]["AdminNovelCommentItem"];

export type NovelVisibility = AdminNovelListItem["visibility"];
type NovelModerationStatus = AdminNovelListItem["moderationStatus"];
export type NovelScreeningOutcome = AdminNovelScreeningItem["outcome"];
type NovelFlaggedPart = AdminNovelScreeningItem["flaggedParts"][number];
type NovelCommentDeletedBy = NonNullable<AdminNovelCommentItem["deletedBy"]>;

/** 게시자가 공개를 거두면 `withdrawn` 이다 — 공개 행과 공개본은 남고 독자에게만 안 보인다. */
export const NOVEL_VISIBILITY_LABELS: Record<NovelVisibility, string> = {
  public: "공개 중",
  withdrawn: "공개 거둠",
};

export const NOVEL_MODERATION_STATUS_LABELS: Record<NovelModerationStatus, string> = {
  normal: "정상",
  restricted: "이용제한",
};

export const NOVEL_SCREENING_OUTCOME_LABELS: Record<NovelScreeningOutcome, string> = {
  passed: "통과",
  rejected: "거절",
};

/** 심사가 걸린 자리. 게시자 화면의 거절 안내와 같은 말이다. */
export const NOVEL_FLAGGED_PART_LABELS: Record<NovelFlaggedPart, string> = {
  novel_title: "소설 제목",
  synopsis: "소개",
  chapter_title: "화 제목",
  author_note: "작가의 말",
  chapter_body: "본문",
};

export const NOVEL_COMMENT_DELETED_BY_LABELS: Record<NovelCommentDeletedBy, string> = {
  author: "작성자",
  publisher: "게시자",
  moderator: "운영자",
};

export function isNovelModerationStatus(value: string): value is NovelModerationStatus {
  return value in NOVEL_MODERATION_STATUS_LABELS;
}

/** 서버 스키마에 상태가 늘면 `NOVEL_MODERATION_STATUS_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 상태가 라우트 검증과 필터에서 조용히 빠진다. 그래서 키에서 도출한다. */
export const NOVEL_MODERATION_STATUS_VALUES = Object.keys(NOVEL_MODERATION_STATUS_LABELS).filter(isNovelModerationStatus);

export const NOVEL_MODERATION_STATUS_OPTIONS = NOVEL_MODERATION_STATUS_VALUES.map((value) => ({
  value,
  label: NOVEL_MODERATION_STATUS_LABELS[value],
}));
