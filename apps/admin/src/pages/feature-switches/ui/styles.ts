/** 섹션 카드 — 모델 배정 화면의 편집·이력 카드와 같은 면이다. */
export const SECTION_CARD_CLASS = "flex flex-col gap-3 rounded-xl border border-border bg-card p-4";

/** 상태 배지는 채움이 아니라 윤곽이다(카드 위 `bg-muted` 채움은 카드와 같은 값이라 사라진다). 잉크 명도는 호출부가 고른다 —
 * 운영자가 손댈 게 생긴 상태(덮어씀)만 `text-foreground`. */
export const OUTLINE_BADGE_CLASS =
  "inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium";

/** 링크로 포커스를 받는 제목. 붙박이 상단바(`lg` 미만 `h-14`)에 가리지 않게 스크롤 여백을 둔다. */
export const FOCUS_TARGET_HEADING_CLASS =
  "scroll-mt-20 rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/** 이 화면의 글자 링크. 유채색은 확인 모달의 확정 버튼 하나에만 쓰므로 링크는 무채색 글자 + 밑줄로 링크임을 보인다. */
export const TEXT_LINK_CLASS =
  "admin-hit-area rounded-sm font-medium text-foreground underline underline-offset-4 outline-none hover:decoration-2 focus-visible:ring-3 focus-visible:ring-ring/50";
