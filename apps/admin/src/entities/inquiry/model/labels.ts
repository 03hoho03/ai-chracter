import type { components } from "@ai-character-chat/api-types";

export type InquiryCategory = components["schemas"]["InquiryCategory"];

export const INQUIRY_CATEGORY_LABELS: Record<InquiryCategory, string> = {
  account: "계정",
  bug: "버그 신고",
  content: "콘텐츠",
  suggestion: "건의",
  other: "기타",
};

export const INQUIRY_STATUS_LABELS: Record<components["schemas"]["InquiryStatus"], string> = {
  pending: "대기중",
  answered: "답변완료",
};

export function isInquiryCategory(value: string): value is InquiryCategory {
  return value in INQUIRY_CATEGORY_LABELS;
}

/** 카테고리가 늘면 `INQUIRY_CATEGORY_LABELS`(Record)가 컴파일 에러로 잡는다 — 목록·옵션을 손으로
 * 또 적으면 그 강제가 목록에는 걸리지 않아 새 카테고리가 조용히 빠진다. 그래서 둘 다 키에서 도출한다
 * (`entities/report/model/labels.ts`의 `REPORT_REASON_LABELS` 동형). */
export const INQUIRY_CATEGORY_VALUES = Object.keys(INQUIRY_CATEGORY_LABELS).filter(isInquiryCategory);

export const INQUIRY_CATEGORY_OPTIONS = INQUIRY_CATEGORY_VALUES.map((value) => ({
  value,
  label: INQUIRY_CATEGORY_LABELS[value],
}));
