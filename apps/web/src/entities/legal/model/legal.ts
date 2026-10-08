import type { components } from "@ai-character-chat/api-types";

import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

/** `GET /legal/{kind}`와 법적 문서 페이지가 다루는 문서 종류. 값이 곧 웹 경로다(`/operation-policy` 등). */
export type LegalDocumentKind = components["schemas"]["LegalDocumentPublicResponse"]["kind"];

/** `POST /legal/consent`가 받는 문서 종류 — 회원 동의를 기록하는 약관·처리방침뿐이다. 재동의 모달은 이 타입만
 * 다룬다. 문서 종류 전체와 섞으면 운영정책 같은 공지성 문서가 동의 흐름에 들어갈 길이 생긴다. */
export type LegalConsentKind = components["schemas"]["LegalConsentRequest"]["kind"];

/** 문서 이름은 헤더 메뉴·푸터 링크 라벨과 같은 문자열이어야 해서 그 목적지 목록에서 가져온다. */
export const LEGAL_DOCUMENT_LABEL: Record<LegalDocumentKind, string> = {
  terms: SUPPORT_DESTINATIONS.terms.label,
  privacy: SUPPORT_DESTINATIONS.privacy.label,
  "operation-policy": SUPPORT_DESTINATIONS["operation-policy"].label,
  "youth-policy": SUPPORT_DESTINATIONS["youth-policy"].label,
  "refund-policy": SUPPORT_DESTINATIONS["refund-policy"].label,
};

/** 동의 종류가 늘면 이 Record가 컴파일 에러로 잡는다 — 목록을 손으로 또 적으면 그 강제가 목록에는 걸리지 않아
 * 새 종류가 조용히 빠진다. 그래서 목록은 키에서 도출한다. */
const IS_LEGAL_CONSENT_KIND: Record<LegalConsentKind, true> = { terms: true, privacy: true };

/** own key만 본다 — `in`은 프로토타입 체인까지 보므로 `"toString"`·`"constructor"`가 통과한다. 좁히기는
 * `Object.hasOwn`이 아니라 명시 반환 타입(`value is …`)이 만든다(`entities/content/model/visibilityFilter.ts` 참고). */
function isLegalConsentKind(value: string): value is LegalConsentKind {
  return Object.hasOwn(IS_LEGAL_CONSENT_KIND, value);
}

export const LEGAL_CONSENT_KINDS = Object.keys(IS_LEGAL_CONSENT_KIND).filter(isLegalConsentKind);
