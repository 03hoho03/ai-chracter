import type { ContentType } from "./content";

/** `ContentCard`의 `thumbnailAspect` prop이 받는 표현형 — 도메인(`ContentType`)과는 `toThumbnailAspect`
 * 하나로만 연결된다(card-grid-techspec.md T-3). */
export type ThumbnailAspect = "square" | "portrait";

/** `ContentCardGrid`의 `thumbnailAspect` prop — 단일 타입 그리드(`ThumbnailAspect`)에 캐릭터·스토리가
 * 섞인 그리드(`/my` 전체 필터)를 더한 것(card-grid-techspec.md T-4). */
export type GridAspect = ThumbnailAspect | "mixed";

/** card-grid-goal-prompt.md D-2 — 썸네일 표시 비율의 도메인→표현 매핑. 스토리는 세로 2:3, 캐릭터는
 * 정사각 — 두 값이 가까우면(예: 세로끼리) 그리드에서 타입이 한눈에 안 갈린다는 게 캐릭터를 1:1로 둔
 * 이유다. 카드는 이 매핑을 모른다 — 호출부가 이 함수를 거쳐 `thumbnailAspect`를 채운다.
 *
 * 삼항이 아니라 `Record`인 것은 exhaustiveness 때문이다(TS-05) — 삼항이면 `ContentType`에 멤버가
 * 늘어도 조용히 `square`로 접히는데, 이 함수가 도메인→표현 매핑의 유일한 소스라 그 침묵이 그대로
 * 전 화면에 퍼진다. `Record`면 멤버가 늘 때 여기서 컴파일이 깨진다. */
const THUMBNAIL_ASPECT: Record<ContentType, ThumbnailAspect> = {
  character: "square",
  story: "portrait",
};

export function toThumbnailAspect(type: ContentType): ThumbnailAspect {
  return THUMBNAIL_ASPECT[type];
}

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

/** 첫 줄에 놓이는 카드 수 = 그 사다리의 **최대 열 수**. 호출부가 `priority`(eager 로드)를 줄 개수다.
 *
 * 열 사다리와 같은 파일에 두는 이유는 **실제로 어긋났기 때문이다** — 2026-09-11 에 portrait 를
 * 3/4/5 로 바꿨는데 호출부 4곳의 `index < 4` 가 그대로 남아 **md 이상에서 첫 줄 마지막(5번째)
 * 카드가 lazy 로 빠졌다.** 손으로 맞춘 값은 사다리를 바꿀 때 따라오지 않는다.
 *
 * `square`·`mixed` 가 4인 것은 그 사다리의 최대가 `md:grid-cols-4` 이기 때문이다. 좁은 화면에서는
 * 실제 열 수보다 많이 당겨지지만(2열이면 2장이 과하게) 그건 원래 감수하던 오차다. */
const MAX_COLUMNS: Record<GridAspect, number> = {
  square: 4,
  portrait: 5,
  mixed: 4,
};

export function toPriorityCount(aspect: GridAspect): number {
  return MAX_COLUMNS[aspect];
}
