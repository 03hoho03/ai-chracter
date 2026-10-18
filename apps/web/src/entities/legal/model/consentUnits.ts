import type { components } from "@ai-character-chat/api-types";

import type { LegalConsentKind } from "./legal";

/** 동의 단위 — 가입 화면이 따로 받는 세 동의(이용약관, 개인정보 수집·이용, 국외이전)와 같다. 처리방침 한 문서에 단위가
 * 둘이라 문서 종류(`LegalConsentKind`)와 따로 둔다. */
export type LegalConsentUnit = components["schemas"]["LegalChangeItem"]["reconsentScopes"][number];

type MeResponse = components["schemas"]["MeResponse"];

/** 재동의 판정에 쓰는 세션 칸. 처리방침 하나로 묶인 옛 플래그(`privacyReconsentRequired`)는 읽지 않는다 — 국외이전만 다시
 * 받는 판에서 수집·이용 체크까지 요구하게 되고, 그 칸은 곧 응답에서 빠진다. */
export type ReconsentFlags = Pick<
  MeResponse,
  "termsReconsentRequired" | "collectionReconsentRequired" | "transferReconsentRequired"
>;

/** 화면에 늘어놓는 순서. 가입 화면의 체크 순서와 같다. */
const CONSENT_UNIT_ORDER = ["terms", "collection", "transfer"] as const satisfies readonly LegalConsentUnit[];

const FLAG_BY_UNIT: Record<LegalConsentUnit, keyof ReconsentFlags> = {
  terms: "termsReconsentRequired",
  collection: "collectionReconsentRequired",
  transfer: "transferReconsentRequired",
};

/** 동의 단위가 어느 문서의 동의인가. 수집·이용과 국외이전은 둘 다 처리방침에 동의하는 것이다. */
export const CONSENT_UNIT_DOCUMENT: Record<LegalConsentUnit, LegalConsentKind> = {
  terms: "terms",
  collection: "privacy",
  transfer: "privacy",
};

/** 체크박스 문구. 가입 화면(`LegalConsentFields`)의 체크 문구와 같게 둔다 — 같은 동의를 두 화면이 다른 이름으로 부르면
 * 회원은 무엇에 다시 동의하는지 대조할 수 없다. */
export const CONSENT_UNIT_LABEL: Record<LegalConsentUnit, string> = {
  terms: "(필수) 이용약관 동의",
  collection: "(필수) 개인정보 수집·이용 동의",
  transfer: "(필수) 개인정보 국외이전 동의",
};

/** 지금 다시 동의를 받아야 하는 단위들(가입 화면 순서). */
export function pendingConsentUnits(flags: ReconsentFlags): LegalConsentUnit[] {
  return CONSENT_UNIT_ORDER.filter((unit) => flags[FLAG_BY_UNIT[unit]]);
}

export function hasPendingReconsent(flags: ReconsentFlags): boolean {
  return pendingConsentUnits(flags).length > 0;
}

/** 다시 동의할 단위들이 걸친 문서(약관 → 처리방침 순, 중복 없음). 모달은 문서마다 카드 하나를 그린다. */
export function pendingConsentDocuments(units: readonly LegalConsentUnit[]): LegalConsentKind[] {
  const documents: LegalConsentKind[] = [];
  for (const unit of units) {
    const document = CONSENT_UNIT_DOCUMENT[unit];
    if (!documents.includes(document)) documents.push(document);
  }
  return documents;
}

/** 한 문서에서 다시 동의할 단위들이 각각 마지막으로 동의한 판. 누적 변경 안내의 기준을 고르는 입력이다. */
export function consentedVersionsFor(
  document: LegalConsentKind,
  units: readonly LegalConsentUnit[],
  versions: MeResponse["legalConsentVersions"],
): (string | null)[] {
  return units.filter((unit) => CONSENT_UNIT_DOCUMENT[unit] === document).map((unit) => versions[unit]);
}
