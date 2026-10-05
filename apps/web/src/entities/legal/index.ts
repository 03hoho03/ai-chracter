export { legalKeys } from "./api/keys";
export { useLegalDocumentQuery } from "./api/useLegalDocumentQuery";
export type { LegalDocumentResponse } from "./api/useLegalDocumentQuery";
export { useLegalConsentMutation } from "./api/useLegalConsentMutation";
export { LEGAL_CONSENT_KINDS, LEGAL_DOCUMENT_LABEL } from "./model/legal";
export type { LegalConsentKind, LegalDocumentKind } from "./model/legal";
export { isLegalReconsentRequiredError } from "./model/isLegalReconsentRequiredError";
