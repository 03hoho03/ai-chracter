import { atom } from "jotai";

// TS-09 — 목록과 유니온 타입은 한쪽에서 도출한다. 값 목록을 단일 소스로 두고 타입·술어를 그 옆에서
// 도출한다(widgets/header/ui/ContentTypeToggle.tsx가 이 술어로 Radix ToggleGroup의 string 값을 좁힌다).
export const CONTENT_TYPE_TOGGLE_VALUES = ["character", "story"] as const;

export type ContentTypeToggleValue = (typeof CONTENT_TYPE_TOGGLE_VALUES)[number];

export function isContentTypeToggleValue(value: string): value is ContentTypeToggleValue {
  return CONTENT_TYPE_TOGGLE_VALUES.some((toggleValue) => toggleValue === value);
}

/**
 * techspec-global-nav-profile.md §1.1 — 헤더 전역 토글 전용 상태. 최초 진입 기본값은 'story'
 * (techspec-overview.md §5, US-007/FR-10). 프로필 페이지의 로컬 토글(?type= 검색 파라미터)과는
 * 완전히 별개이므로 혼동해서 재사용하지 않는다.
 */
export const contentTypeToggleAtom = atom<ContentTypeToggleValue>("story");
