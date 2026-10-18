import type { components } from "@ai-character-chat/api-types";

export type LegalKind = components["schemas"]["AdminLegalDocumentResponse"]["kind"];

/** 스키마에 kind가 늘면 이 `Record`가 컴파일 에러로 잡는다 — 목록·술어를 손으로 또 적지 않고
 * 여기서 도출해야 셋이 어긋날 수 없다. */
export const LEGAL_KIND_LABELS: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
  "operation-policy": "운영정책",
  "youth-policy": "청소년 보호정책",
  "refund-policy": "환불정책",
  "creator-payout-policy": "크리에이터 정산 정책",
};

export type LegalConsentUnit = NonNullable<components["schemas"]["AdminLegalPublishRequest"]["reconsentScopes"]>[number];

export const CONSENT_UNIT_LABELS: Record<LegalConsentUnit, string> = {
  terms: "이용약관",
  collection: "개인정보 수집·이용",
  transfer: "개인정보 국외이전",
};

/** 동의 단위 목록을 따로 적지 않고 위 `Record`(스키마의 동의 단위를 빠짐없이 요구한다)에서 판정한다. */
export function isLegalConsentUnit(value: unknown): value is LegalConsentUnit {
  return typeof value === "string" && Object.hasOwn(CONSENT_UNIT_LABELS, value);
}

/** 게시할 때 다시 받을 수 있는 동의 단위. 회원 동의를 기록하는 문서는 약관(약관 동의)과 처리방침(수집·이용, 국외이전)뿐이라
 * 정책 문서는 빈 목록이다 — 그 밖의 범위를 보내면 서버가 422 로 거부한다. 종류가 늘면 이 `Record`가 컴파일 에러로 그
 * 종류의 답을 요구한다. 순서는 서버가 범위를 돌려주는 순서(약관 → 수집·이용 → 국외이전)와 같다. */
const RECONSENT_SCOPES_BY_KIND: Record<LegalKind, readonly LegalConsentUnit[]> = {
  terms: ["terms"],
  privacy: ["collection", "transfer"],
  "operation-policy": [],
  "youth-policy": [],
  "refund-policy": [],
  "creator-payout-policy": [],
};

export function reconsentScopesOf(kind: LegalKind): readonly LegalConsentUnit[] {
  return RECONSENT_SCOPES_BY_KIND[kind];
}

/** 이력·요약 칸에 쓰는 범위 문구. 범위가 없으면 "없음". */
export function formatReconsentScopes(scopes: readonly LegalConsentUnit[]): string {
  return scopes.length === 0 ? "없음" : scopes.map((scope) => CONSENT_UNIT_LABELS[scope]).join(", ");
}

export function isLegalKind(value: string): value is LegalKind {
  return value in LEGAL_KIND_LABELS;
}

export const LEGAL_KINDS = Object.keys(LEGAL_KIND_LABELS).filter(isLegalKind);
