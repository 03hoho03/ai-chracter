import type { components } from "@ai-character-chat/api-types";

export type ReportReasonCategory = components["schemas"]["ReportReasonCategory"];

export const REPORT_REASON_LABELS: Record<ReportReasonCategory, string> = {
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

export function isReportReasonCategory(value: string): value is ReportReasonCategory {
  return value in REPORT_REASON_LABELS;
}

/** 사유가 늘면 `REPORT_REASON_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 사유가 조용히 빠진다. 그래서 둘 다 키에서 도출한다. */
export const REPORT_REASON_VALUES = Object.keys(REPORT_REASON_LABELS).filter(isReportReasonCategory);

export const REPORT_REASON_OPTIONS = REPORT_REASON_VALUES.map((value) => ({
  value,
  label: REPORT_REASON_LABELS[value],
}));

/** 채팅 응답 신고는 작품·댓글 신고와 다른 사유 체계다(AI 응답의 품질·안전 사유). BE 스키마에 이름 붙은
 * enum이 없고 필드에 리터럴 유니언으로만 있어 그 필드에서 타입을 뽑는다. `Record`라 사유가 늘면
 * 컴파일이 잡는다. 문구는 웹 신고 모달과 같은 말이다(별도 번들이라 맵은 앱마다 둔다). */
export type ChatMessageReportReason = components["schemas"]["AdminChatMessageReportListItem"]["reason"];

export const CHAT_MESSAGE_REPORT_REASON_LABELS: Record<ChatMessageReportReason, string> = {
  inappropriate: "부적절·선정적",
  hateful: "혐오·공격적",
  out_of_character: "캐릭터·설정 붕괴",
  repetitive: "반복·어색한 문장",
  broken: "깨짐·오류",
  other: "기타",
};

/** 신고 목록·상세 라우트의 `?target=` 값. 두 라우트의 search 스키마와 화면 분기가 모두 이 목록을 본다 —
 * 한쪽 라우트에만 값을 더하면 `.catch(undefined)`가 새 값을 조용히 삼켜 기본값(작품 신고)으로 열린다. */
export const REPORT_TARGETS = ["content", "comment", "chat-message"] as const;

export type ReportTarget = (typeof REPORT_TARGETS)[number];

export const REPORT_TARGET_LABELS: Record<ReportTarget, string> = {
  content: "작품 신고",
  comment: "댓글 신고",
  "chat-message": "채팅 응답 신고",
};

export function isReportTarget(value: string): value is ReportTarget {
  return REPORT_TARGETS.some((target) => target === value);
}
