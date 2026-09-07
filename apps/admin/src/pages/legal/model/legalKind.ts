import type { components } from "@ai-character-chat/api-types";

export type LegalKind = components["schemas"]["AdminLegalDocumentResponse"]["kind"];

/** 스키마에 kind가 늘면 이 `Record`가 컴파일 에러로 잡는다 — 목록·술어를 손으로 또 적지 않고
 * 여기서 도출해야 셋이 어긋날 수 없다. */
export const LEGAL_KIND_LABELS: Record<LegalKind, string> = {
  terms: "이용약관",
  privacy: "개인정보처리방침",
};

export function isLegalKind(value: string): value is LegalKind {
  return value in LEGAL_KIND_LABELS;
}

export const LEGAL_KINDS = Object.keys(LEGAL_KIND_LABELS).filter(isLegalKind);
