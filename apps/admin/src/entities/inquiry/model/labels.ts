import type { components } from "@ai-character-chat/api-types";

export type InquiryCategory = components["schemas"]["InquiryCategory"];
export type InquiryStatus = components["schemas"]["InquiryStatus"];

export const INQUIRY_CATEGORY_LABELS: Record<InquiryCategory, string> = {
  account: "계정",
  bug: "버그 신고",
  content: "콘텐츠",
  suggestion: "건의",
  other: "기타",
};

export const INQUIRY_STATUS_LABELS: Record<InquiryStatus, string> = {
  pending: "대기중",
  answered: "답변완료",
};

export function isInquiryCategory(value: string): value is InquiryCategory {
  return value in INQUIRY_CATEGORY_LABELS;
}

export function isInquiryStatus(value: string): value is InquiryStatus {
  return value in INQUIRY_STATUS_LABELS;
}

/** 카테고리·상태가 늘면 각 `*_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로
 * 또 적으면 그 강제가 목록에는 걸리지 않아 새 멤버가 조용히 빠진다. 그래서 둘 다 키에서 도출한다
 * (`entities/report/model/labels.ts`의 `REPORT_REASON_LABELS` 동형). */
export const INQUIRY_CATEGORY_VALUES = Object.keys(INQUIRY_CATEGORY_LABELS).filter(isInquiryCategory);

export const INQUIRY_CATEGORY_OPTIONS = INQUIRY_CATEGORY_VALUES.map((value) => ({
  value,
  label: INQUIRY_CATEGORY_LABELS[value],
}));

export const INQUIRY_STATUS_VALUES = Object.keys(INQUIRY_STATUS_LABELS).filter(isInquiryStatus);

export const INQUIRY_STATUS_OPTIONS = INQUIRY_STATUS_VALUES.map((value) => ({
  value,
  label: INQUIRY_STATUS_LABELS[value],
}));
