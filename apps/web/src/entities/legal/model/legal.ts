import type { components } from "@ai-character-chat/api-types";

import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

/** `GET /legal/{kind}` · `POST /legal/consent`이 공유하는 문서 종류. */
export type LegalDocumentKind = components["schemas"]["LegalConsentRequest"]["kind"];

/** 문서 이름은 헤더 메뉴·푸터 링크 라벨과 같은 문자열이어야 해서 그 목적지 목록에서 가져온다. */
export const LEGAL_DOCUMENT_LABEL: Record<LegalDocumentKind, string> = {
  terms: SUPPORT_DESTINATIONS.terms.label,
  privacy: SUPPORT_DESTINATIONS.privacy.label,
};

/** 현재 호출부는 `Object.keys(...)` 결과만 넘겨 `in`과 `hasOwn`이 갈리지 않지만, 이 술어는 public API라 외부 입력이
 * 닿는 순간을 대비해 own key만 본다 — `in`은 프로토타입 체인까지 보므로 `"toString"`·`"constructor"`가 통과한다.
 * 좁히기는 `Object.hasOwn`이 아니라 명시 반환 타입(`value is …`)이 만든다(`entities/content/model/visibilityFilter.ts` 참고). */
export function isLegalDocumentKind(value: string): value is LegalDocumentKind {
  return Object.hasOwn(LEGAL_DOCUMENT_LABEL, value);
}

/** 스키마에 kind가 늘면 `LEGAL_DOCUMENT_LABEL`이 컴파일 에러로 잡는다 — 목록을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 문서가 조용히 빠진다. 그래서 키에서 도출한다. */
export const LEGAL_DOCUMENT_KINDS = Object.keys(LEGAL_DOCUMENT_LABEL).filter(isLegalDocumentKind);
