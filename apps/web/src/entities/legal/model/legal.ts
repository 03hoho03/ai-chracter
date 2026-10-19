import type { components } from "@ai-character-chat/api-types";

import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

/** `GET /legal/{kind}`와 법적 문서 페이지가 다루는 문서 종류. 값이 곧 웹 경로다(`/operation-policy` 등). */
export type LegalDocumentKind = components["schemas"]["LegalDocumentPublicResponse"]["kind"];

/** 회원이 동의하는 문서 — 약관·처리방침뿐이다. 재동의 모달은 이 타입만 다룬다. 문서 종류 전체와 섞으면 운영정책 같은
 * 공지성 문서가 동의 흐름에 들어갈 길이 생긴다. 동의 요청 바디의 옛 `kind` 칸에서 도출하지 않는다 — 그 칸은 동의 단위
 * 목록(`consents`)으로 바뀌어 곧 스키마에서 빠진다. */
export type LegalConsentKind = Extract<LegalDocumentKind, "terms" | "privacy">;

/** 문서 이름은 헤더 메뉴·푸터 링크 라벨과 같은 문자열이어야 해서 그 목적지 목록에서 가져온다. */
export const LEGAL_DOCUMENT_LABEL: Record<LegalDocumentKind, string> = {
  terms: SUPPORT_DESTINATIONS.terms.label,
  privacy: SUPPORT_DESTINATIONS.privacy.label,
  "operation-policy": SUPPORT_DESTINATIONS["operation-policy"].label,
  "youth-policy": SUPPORT_DESTINATIONS["youth-policy"].label,
  "refund-policy": SUPPORT_DESTINATIONS["refund-policy"].label,
  "creator-payout-policy": SUPPORT_DESTINATIONS["creator-payout-policy"].label,
};
