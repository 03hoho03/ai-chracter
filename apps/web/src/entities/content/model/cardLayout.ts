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

// `portrait`만 `lg:` 단계를 갖는 이유(card-grid-goal-prompt.md D-5) — 390px 3열이면 카드 폭이 111.3px로
// 줄어 텍스트 가용폭이 85.3px, 작가명에는 21.9px(한글 1.8자)만 남는다. **카드 폭 ≥ 138px**이 작가명
// 4자의 하한이고 이 사다리는 전 구간에서 이를 넘는다(390:173 · 640:189 · 768:171 · 1024:186px, canvas
// 실측 — 한글 1자 ≈ 12.1px @14px Pretendard).
const PORTRAIT_COLUMNS = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5";

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
