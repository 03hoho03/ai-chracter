import type { GridAspect, ThumbnailAspect } from "../model/cardLayout";

/** 표현형 → Tailwind 클래스. `ContentCard`와 `ContentCardSkeleton`이 같은 삼항을 각자 들고 있었는데,
 * 스켈레톤이 카드의 높이를 그대로 흉내 내는 구조(card-grid-techspec.md T-5)라 **둘이 어긋나는 순간
 * 스켈레톤 높이가 틀어진다** — 한 곳에서만 정한다. `aspect-story`는 `globals.css`의 `--aspect-story`
 * 토큰(2:3)이고 `aspect-square`는 Tailwind 기본이다. */
const THUMBNAIL_ASPECT_CLASS: Record<ThumbnailAspect, string> = {
  square: "aspect-square",
  portrait: "aspect-story",
};

export function toThumbnailAspectClass(aspect: ThumbnailAspect): string {
  return THUMBNAIL_ASPECT_CLASS[aspect];
}

const SQUARE_COLUMNS = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4";

// `portrait`이 390px부터 3열인 이유(card-grid-goal-prompt.md D-5 갱신, 2026-09-11) — 예전엔 "패딩을
// 남기기로 해서 3열을 못 쓴다"였는데, 카드 껍데기(border+텍스트 영역 p-3)가 걷히며 그 전제가 사라졌다.
// 텍스트가 이제 카드 폭 전체를 쓴다: 고정비용(Eye 14 + gap 4 + `1,234` 34.8 + ` · ` 10.6 = 63.4px)을
// 뺀 나머지가 작가명 몫이고, 한글 1자 ≈ 12.1px @14px Pretendard(canvas 실측)다. 390:3열(카드 폭=텍스트
// 폭 111.33px, 작가명 47.9px=3.96자) · 640:4열(139px, 75.6px=6.2자) · 768:5열(134.4px, 71px=5.9자) ·
// 1024:5열(185.6px, 122.2px=10자) — 전 구간에서 작가명이 최소 3.96자를 유지한다. **이 숫자를 다시
// 인용하기 전에 카드에 패딩이 없다는 전제부터 확인할 것** — 패딩이 돌아오면 3열은 다시 못 쓴다.
const PORTRAIT_COLUMNS = "grid-cols-3 sm:grid-cols-4 md:grid-cols-5";

// `mixed`의 `items-start` — 없으면 grid 기본 `stretch`가 짧은 카드(캐릭터 245px)를 긴 카드
// (스토리 331px) 높이까지 늘려 **빈 border 상자**가 생긴다(card-grid-goal-prompt.md D-6).
const MIXED_COLUMNS = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 items-start";

const GRID_COLUMNS: Record<GridAspect, string> = {
  square: SQUARE_COLUMNS,
  portrait: PORTRAIT_COLUMNS,
  mixed: MIXED_COLUMNS,
};

/** card-grid-techspec.md T-4 — 그리드 열 수는 타입별로 갈린다(D-5). `ContentCardGrid`가 이 함수 하나로
 * 열 클래스를 정한다. */
export function toGridColumns(aspect: GridAspect): string {
  return GRID_COLUMNS[aspect];
}
