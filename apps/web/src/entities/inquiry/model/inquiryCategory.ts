import type { components } from "@ai-character-chat/api-types";

export type InquiryCategory = components["schemas"]["InquiryCategory"];

export const INQUIRY_CATEGORY_LABEL: Record<InquiryCategory, string> = {
  account: "계정·로그인",
  bug: "버그 신고",
  content: "콘텐츠·신고",
  suggestion: "제안",
  other: "기타",
};

/** 현재 호출부는 `Object.keys(...)` 결과만 넘겨 `in`과 `hasOwn`이 갈리지 않지만, 이 술어는 public API라 외부 입력이
 * 닿는 순간을 대비해 own key만 본다 — `in`은 프로토타입 체인까지 보므로 `"toString"`·`"constructor"`가 통과한다.
 * 좁히기는 `Object.hasOwn`이 아니라 명시 반환 타입(`value is …`)이 만든다(`entities/content/model/visibilityFilter.ts` 참고). */
export function isInquiryCategory(value: string): value is InquiryCategory {
  return Object.hasOwn(INQUIRY_CATEGORY_LABEL, value);
}

/** 스키마에 카테고리가 늘면 `INQUIRY_CATEGORY_LABEL`이 컴파일 에러로 잡는다 — 목록을 손으로
 * 또 적으면 그 강제가 목록에는 걸리지 않아 새 값이 조용히 빠진다. 그래서 키에서 도출한다. */
export const INQUIRY_CATEGORIES = Object.keys(INQUIRY_CATEGORY_LABEL).filter(isInquiryCategory);
