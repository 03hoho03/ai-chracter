export { legalKeys } from "./api/keys";
export { useLegalDocumentQuery } from "./api/useLegalDocumentQuery";
export type { LegalDocumentResponse } from "./api/useLegalDocumentQuery";
export { useLegalChangesQuery } from "./api/useLegalChangesQuery";
export { useLegalUpcomingDocumentQuery } from "./api/useLegalUpcomingDocumentQuery";
export { useLegalConsentMutation } from "./api/useLegalConsentMutation";
export { LEGAL_DOCUMENT_LABEL } from "./model/legal";
export type { LegalConsentKind, LegalDocumentKind } from "./model/legal";
export {
  CONSENT_UNIT_LABEL,
  consentedVersionsFor,
  hasPendingReconsent,
  pendingConsentDocuments,
  pendingConsentUnits,
} from "./model/consentUnits";
export type { LegalConsentUnit, ReconsentFlags } from "./model/consentUnits";
export { selectChangesSinceOldestConsent, toChangeNoticeEntries } from "./model/legalChanges";
export type { ChangeNoticeEntry } from "./model/legalChanges";
export { isLegalReconsentRequiredError } from "./model/isLegalReconsentRequiredError";
