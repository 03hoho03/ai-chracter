import type { LegalKind } from "../model/legalKind";

export const legalKeys = {
  all: ["legal"] as const,
  detail: (kind: LegalKind) => [...legalKeys.all, "detail", kind] as const,
  versions: (kind: LegalKind) => [...legalKeys.all, "versions", kind] as const,
};
