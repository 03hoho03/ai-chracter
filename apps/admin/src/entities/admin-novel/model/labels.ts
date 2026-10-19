import type { components } from "@ai-character-chat/api-types";

type AdminNovelListItem = components["schemas"]["AdminNovelListItem"];
type AdminNovelScreeningItem = components["schemas"]["AdminNovelScreeningItem"];
type AdminNovelCommentItem = components["schemas"]["AdminNovelCommentItem"];
type AdminNovelDetailResponse = components["schemas"]["AdminNovelDetailResponse"];

export type NovelVisibility = AdminNovelListItem["visibility"];
type NovelModerationStatus = AdminNovelListItem["moderationStatus"];
export type NovelScreeningOutcome = AdminNovelScreeningItem["outcome"];
type NovelFlaggedPart = AdminNovelScreeningItem["flaggedParts"][number];
type NovelCommentDeletedBy = NonNullable<AdminNovelCommentItem["deletedBy"]>;
export type NovelReviewStatus = NonNullable<AdminNovelListItem["reviewStatus"]>;
type NovelSerialLockSource = NonNullable<AdminNovelDetailResponse["serialLockSource"]>;
type NovelSerialLockPermission = NonNullable<AdminNovelDetailResponse["serialLockPermission"]>;

/** 게시자가 공개를 거두면 `withdrawn` 이다 — 공개 행과 공개본은 남고 독자에게만 안 보인다. */
export const NOVEL_VISIBILITY_LABELS: Record<NovelVisibility, string> = {
  public: "공개 중",
  withdrawn: "공개 거둠",
};

export const NOVEL_MODERATION_STATUS_LABELS: Record<NovelModerationStatus, string> = {
  normal: "정상",
  restricted: "이용제한",
};

/** 첫 공개 운영자 심사. 심사가 없던 시절의 공개와 스위치가 꺼진 동안의 공개는 값이 없다(`null`). 대기·반려 행은 공개 범위가
 * `withdrawn` 이라, 목록·상세는 이 라벨을 공개 범위 라벨 대신 앞세워 "게시자가 거둠"으로 읽히지 않게 한다. */
export const NOVEL_REVIEW_STATUS_LABELS: Record<NovelReviewStatus, string> = {
  pending: "승인 대기",
  approved: "승인",
  rejected: "반려",
};

/** 연재권이 잠긴 경로. 첫 공개 승인 때 찍히거나, 심사가 생기기 전에 이미 공개된 소설에 일괄로 찍혔다. */
export const NOVEL_SERIAL_LOCK_SOURCE_LABELS: Record<NovelSerialLockSource, string> = {
  first_publish: "첫 공개",
  backfill: "이전 공개 일괄 기록",
};

/** 잠글 때의 원작 허락 단계. 웹의 작품 설정 화면이 작가에게 보이는 단계 이름과 같은 말을 쓴다. */
export const NOVEL_SERIAL_LOCK_PERMISSION_LABELS: Record<NovelSerialLockPermission, string> = {
  forbidden: "허용 안 함",
  private: "나만 보는 소설",
  public: "공개 소설까지",
};

/** 목록 행·상세 머리 줄의 공개 상태 한 마디. 승인 대기·반려는 공개 범위가 `withdrawn` 이어도 게시자가 거둔 것이 아니므로
 * 심사 라벨을 대신 낸다. 승인됐거나 심사가 없던 공개는 공개 범위 라벨 그대로다. */
export function novelPublicationLabel(novel: {
  visibility: NovelVisibility;
  reviewStatus: NovelReviewStatus | null;
}): string {
  if (novel.reviewStatus === "pending" || novel.reviewStatus === "rejected") {
    return NOVEL_REVIEW_STATUS_LABELS[novel.reviewStatus];
  }
  return NOVEL_VISIBILITY_LABELS[novel.visibility];
}

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

export function isNovelReviewStatus(value: string): value is NovelReviewStatus {
  return value in NOVEL_REVIEW_STATUS_LABELS;
}

/** 이용제한 값 목록과 같은 이유로 라벨 Record 키에서 도출한다. */
export const NOVEL_REVIEW_STATUS_VALUES = Object.keys(NOVEL_REVIEW_STATUS_LABELS).filter(isNovelReviewStatus);

export const NOVEL_REVIEW_STATUS_OPTIONS = NOVEL_REVIEW_STATUS_VALUES.map((value) => ({
  value,
  label: NOVEL_REVIEW_STATUS_LABELS[value],
}));
