import type { components } from "@ai-character-chat/api-types";

export type LegalKind = components["schemas"]["AdminLegalDocumentResponse"]["kind"];

/** 스키마에 kind가 늘면 이 `Record`가 컴파일 에러로 잡는다 — 목록·술어를 손으로 또 적지 않고
 * 여기서 도출해야 셋이 어긋날 수 없다. */
export const LEGAL_KIND_LABELS: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
  "operation-policy": "운영정책",
  "youth-policy": "청소년 보호정책",
};

/** 게시할 때 회원 재동의를 요구할 수 있는 문서인지. 회원 동의를 기록하는 문서는 약관·처리방침뿐이라 나머지에
 * 재동의를 걸어도 재동의 게이트는 반응하지 않고, 서버도 그 게시를 422로 거부한다. 종류가 늘면 이 `Record`가
 * 컴파일 에러로 그 종류의 답을 요구한다. */
const CAN_REQUIRE_RECONSENT: Record<LegalKind, boolean> = {
  terms: true,
  privacy: true,
  "operation-policy": false,
  "youth-policy": false,
};

export function canRequireReconsent(kind: LegalKind): boolean {
  return CAN_REQUIRE_RECONSENT[kind];
}

export function isLegalKind(value: string): value is LegalKind {
  return value in LEGAL_KIND_LABELS;
}

export const LEGAL_KINDS = Object.keys(LEGAL_KIND_LABELS).filter(isLegalKind);
