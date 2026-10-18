import type { LegalDocumentKind } from "../model/legal";

export const legalKeys = {
  all: ["legal"] as const,
  document: (kind: LegalDocumentKind) => [...legalKeys.all, "document", kind] as const,
  upcoming: (kind: LegalDocumentKind) => [...legalKeys.all, "upcoming", kind] as const,
  changes: (kind: LegalDocumentKind) => [...legalKeys.all, "changes", kind] as const,
};
