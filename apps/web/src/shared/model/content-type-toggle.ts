import { atom } from "jotai";

export type ContentTypeToggleValue = "character" | "story";

/**
 * techspec-global-nav-profile.md §1.1 — 헤더 전역 토글 전용 상태. 최초 진입 기본값은 'story'
 * (techspec-overview.md §5, US-007/FR-10). 프로필 페이지의 로컬 토글(?type= 검색 파라미터)과는
 * 완전히 별개이므로 혼동해서 재사용하지 않는다.
 */
export const contentTypeToggleAtom = atom<ContentTypeToggleValue>("story");
