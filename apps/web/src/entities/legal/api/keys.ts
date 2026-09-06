import type { LegalDocumentKind } from "../model/legal";

export const legalKeys = {
  all: ["legal"] as const,
  document: (kind: LegalDocumentKind) => [...legalKeys.all, "document", kind] as const,
};
