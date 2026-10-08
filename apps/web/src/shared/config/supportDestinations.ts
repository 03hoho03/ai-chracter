/**
 * 서비스 정보·고객센터 목적지의 라벨과 경로를 정하는 단일 소스. 헤더 메뉴·모바일 드로어·사이트 푸터가 모두
 * 여기서 읽는다 — 각자 라벨과 경로를 적으면 한쪽에만 고쳐져 같은 페이지가 자리마다 다른 이름으로 불린다.
 * 라벨은 도착 페이지의 h1 과 같은 문자열이다(법적 문서 이름도 여기서 가져간다).
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
  "operation-policy": { label: "운영정책", to: "/operation-policy", isPublic: true },
  "youth-policy": { label: "청소년 보호정책", to: "/youth-policy", isPublic: true },
  "refund-policy": { label: "환불정책", to: "/refund-policy", isPublic: true },
  "clover-pricing": { label: "클로버 상품 안내", to: "/clover/pricing", isPublic: true },
} as const satisfies Record<string, { label: string; to: string; isPublic: boolean }>;

export type SupportDestinationKey = keyof typeof SUPPORT_DESTINATIONS;

export type PublicSupportDestinationKey = {
  [Key in SupportDestinationKey]: (typeof SUPPORT_DESTINATIONS)[Key]["isPublic"] extends true ? Key : never;
}[SupportDestinationKey];

/** 공개 키 중 받은 타입에 들어가는 것으로 좁힌다. 헤더 메뉴의 키 목록은 이 목록의 일부만 담으므로, 좁힌 결과가
 * 이 목록 전체의 공개 키면 그 목록 원소 타입의 부분집합이 아니게 되어 `Array.filter`가 좁히지 못한다. 거꾸로
 * 받은 타입 쪽을 걸러 내면(`Extract<Key, ...>`) 넓은 `string`은 어떤 공개 키에도 들어가지 않아 `never`가 된다. */
export function isPublicSupportDestinationKey<Key extends string>(
  key: Key,
): key is Extract<PublicSupportDestinationKey, Key> {
  return Object.entries(SUPPORT_DESTINATIONS).some(([candidate, destination]) => candidate === key && destination.isPublic);
}
