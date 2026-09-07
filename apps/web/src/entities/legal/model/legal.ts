import type { components } from "@ai-character-chat/api-types";

/** `GET /legal/{kind}` · `POST /legal/consent`이 공유하는 문서 종류. */
export type LegalDocumentKind = components["schemas"]["LegalConsentRequest"]["kind"];

export const LEGAL_DOCUMENT_LABEL: Record<LegalDocumentKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
};

export function isLegalDocumentKind(value: string): value is LegalDocumentKind {
  return value in LEGAL_DOCUMENT_LABEL;
}

/** 스키마에 kind가 늘면 `LEGAL_DOCUMENT_LABEL`이 컴파일 에러로 잡는다 — 목록을 손으로 또 적으면
 * 그 강제가 목록에는 걸리지 않아 새 문서가 조용히 빠진다. 그래서 키에서 도출한다. */
export const LEGAL_DOCUMENT_KINDS = Object.keys(LEGAL_DOCUMENT_LABEL).filter(isLegalDocumentKind);
