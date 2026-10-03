/**
 * 서비스 정보·고객센터 목적지의 라벨과 경로를 정하는 단일 소스. 헤더 메뉴·모바일 드로어·사이트 푸터가 모두
 * 여기서 읽는다 — 각자 라벨과 경로를 적으면 한쪽에만 고쳐져 같은 페이지가 자리마다 다른 이름으로 불린다.
 * 라벨은 도착 페이지의 h1 과 같은 문자열이다(약관·처리방침 문서 이름도 여기서 가져간다).
 *
 * `isPublic`은 로그인 없이 열리는 라우트인지다. 비로그인 드로어가 이 값으로 목록을 고른다 — 로그인이 필요한
 * 라우트(`문의하기`)를 비로그인에게 보여 주면 누르자마자 로그인 화면으로 튕긴다.
 */
export const SUPPORT_DESTINATIONS = {
  about: { label: "서비스 소개", to: "/about", isPublic: true },
  notices: { label: "공지사항", to: "/notices", isPublic: true },
  "inquiry-new": { label: "문의하기", to: "/inquiries/new", isPublic: false },
  terms: { label: "이용약관", to: "/terms", isPublic: true },
  privacy: { label: "개인정보처리방침", to: "/privacy", isPublic: true },
} as const satisfies Record<string, { label: string; to: string; isPublic: boolean }>;

export type SupportDestinationKey = keyof typeof SUPPORT_DESTINATIONS;

export type PublicSupportDestinationKey = {
  [Key in SupportDestinationKey]: (typeof SUPPORT_DESTINATIONS)[Key]["isPublic"] extends true ? Key : never;
}[SupportDestinationKey];

export function isPublicSupportDestinationKey(key: string): key is PublicSupportDestinationKey {
  return Object.entries(SUPPORT_DESTINATIONS).some(([candidate, destination]) => candidate === key && destination.isPublic);
}
