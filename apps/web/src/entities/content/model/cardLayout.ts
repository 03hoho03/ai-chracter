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

/** 첫 줄에 놓이는 카드 수 = 그 사다리의 최대 열 수. 호출부가 `priority`(eager 로드)를 줄 개수다.
 *
 * `ui/cardLayoutClass.ts`의 열 사다리(`GRID_COLUMNS`)와 값이 어긋나면 안 된다 — 2026-09-11 에 portrait 를
 * 3/4/5 로 바꿨는데 호출부 4곳의 `index < 4` 가 그대로 남아 md 이상에서 첫 줄 마지막(5번째)
 * 카드가 lazy 로 빠졌다. 손으로 맞춘 값은 사다리를 바꿀 때 따라오지 않는다.
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
