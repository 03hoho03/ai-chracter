import type { components } from "@ai-character-chat/api-types";

/** `GET /legal/{kind}` · `POST /legal/consent`이 공유하는 문서 종류. */
export type LegalDocumentKind = components["schemas"]["LegalConsentRequest"]["kind"];

export const LEGAL_DOCUMENT_LABEL: Record<LegalDocumentKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
};
