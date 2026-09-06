import type { components } from "@ai-character-chat/api-types";

export type LegalKind = components["schemas"]["AdminLegalDocumentResponse"]["kind"];

export const LEGAL_KIND_LABELS: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
};

export const legalKeys = {
  all: ["legal"] as const,
  detail: (kind: LegalKind) => [...legalKeys.all, "detail", kind] as const,
  versions: (kind: LegalKind) => [...legalKeys.all, "versions", kind] as const,
};
