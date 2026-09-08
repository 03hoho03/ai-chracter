import type { components } from "@ai-character-chat/api-types";

export type InquiryStatus = components["schemas"]["InquiryStatus"];

export const INQUIRY_STATUS_LABEL: Record<InquiryStatus, string> = {
  pending: "대기",
  answered: "답변완료",
};

/** 상태 배지는 **채움이 아니라 윤곽**이다(DESIGN.md §Status badges) — `bg-muted` 채움은
 * `hover:bg-muted`가 걸린 카드 위에서 표면과 같은 값이 되어(실측 1.0000:1) 알약이 통째로 사라진다.
 * 윤곽(`border-border`)은 hover에서도 살아남는다(다크 1.2993 / 라이트 1.2751).
 *
 * 두 상태를 가르는 건 색이 아니라 **잉크 명도**다 — PRODUCT.md가 "UI 자체(배경/텍스트/버튼/배지)는
 * 무채색"으로 못박아 배지에 유채색을 쓸 수 없고, 이 시스템의 깊이는 원래 명도 사다리가 만든다.
 * `답변완료`는 사용자가 **읽을 게 생긴** 상태라 밝기 천장(`foreground`)까지 올리고(다크 15.79:1 /
 * 라이트 17.31:1), `대기`는 기다리는 것 말고 할 게 없는 정지 상태라 `muted-foreground`에 둔다
 * (6.74:1 / 5.28:1 — 11px 본문 기준 AA 통과). */
export const INQUIRY_STATUS_BADGE_INK: Record<InquiryStatus, string> = {
  pending: "text-muted-foreground",
  answered: "text-foreground",
};
