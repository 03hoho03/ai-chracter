import type { components } from "@ai-character-chat/api-types";

export type InquiryCategory = components["schemas"]["InquiryCategory"];

export const INQUIRY_CATEGORY_LABEL: Record<InquiryCategory, string> = {
  account: "계정·로그인",
  bug: "버그 신고",
  content: "콘텐츠·신고",
  suggestion: "제안",
  other: "기타",
};

export function isInquiryCategory(value: string): value is InquiryCategory {
  return value in INQUIRY_CATEGORY_LABEL;
}

/** 스키마에 카테고리가 늘면 `INQUIRY_CATEGORY_LABEL`이 컴파일 에러로 잡는다 — 목록을 손으로
 * 또 적으면 그 강제가 목록에는 걸리지 않아 새 값이 조용히 빠진다. 그래서 키에서 도출한다. */
export const INQUIRY_CATEGORIES = Object.keys(INQUIRY_CATEGORY_LABEL).filter(isInquiryCategory);
