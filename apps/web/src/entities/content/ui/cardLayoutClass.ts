import type { GridAspect, ThumbnailAspect } from "../model/cardLayout";

/** 표현형 → Tailwind 클래스. `ContentCard`와 `ContentCardSkeleton`이 같은 삼항을 각자 들고 있었는데,
 * 스켈레톤이 카드의 높이를 그대로 흉내 내는 구조라 **둘이 어긋나는 순간
 * 스켈레톤 높이가 틀어진다** — 한 곳에서만 정한다. `aspect-story`는 `globals.css`의 `--aspect-story`
 * 토큰(2:3)이고 `aspect-square`는 Tailwind 기본이다. */
const THUMBNAIL_ASPECT_CLASS: Record<ThumbnailAspect, string> = {
  square: "aspect-square",
  portrait: "aspect-story",
};

export function toThumbnailAspectClass(aspect: ThumbnailAspect): string {
  return THUMBNAIL_ASPECT_CLASS[aspect];
}

// 열 사다리(square·mixed 2/3/4, portrait 3/4/5)는 뷰포트가 아니라 그리드가 받는 폭으로 오른다(컨테이너 쿼리).
// `lg` 이상에서는 왼쪽 패널(펼침·레일)이 뷰포트 폭의 일부를 가져가서, 같은 뷰포트에서도 그리드가 받는 폭이 패널
// 상태에 따라 달라진다. 열 수는 카드가 실제로 받는 폭으로 정해야 카드 폭(과 그 안의 작가명 글자 수)이 예측 가능하다.
//
// 경계 37rem(592px)·45rem(720px)은 뷰포트 경계 `sm`(640)·`md`(768)에서 페이지 거터(좌우 24px씩)를 뺀 그리드 폭이다.
// 그래서 패널이 없는 화면은 지금까지와 같은 폭에서 같은 열이 나온다. 단 `sm` 미만은 거터가 16px씩이라 그리드
// 592~607px 가 뷰포트 624~639px 에서도 나오고, 그 띠만 한 단계 일찍(2→3, portrait 3→4) 는다 — 그 띠의 portrait 4열
// 카드는 139~143px 라 뷰포트 640px 의 4열 카드(139px)보다 좁아지지 않는다. 경계를 38rem(608px)으로 올리면 이번엔 뷰포트
// 640~655px 에서 열이 3→2 로 줄어, 화면이 넓어지는데 열이 줄어드는 구간이 생긴다. 패널이 있는 `lg` 이상의 그리드는
// 가장 좁을 때(1024px 펼침)도 736px 라 늘 마지막 단계다. rem 으로 적는 것은 뷰포트 `sm:`/`md:` 도 rem 이라 기본 글자
// 크기가 16px 가 아닐 때도 같은 쪽으로 움직이게 하려는 것이다.
//
// 컨테이너 쿼리라 이 클래스를 받는 요소는 `@container` 조상 안에 있어야 한다 — 없으면 `@min-*` 이 하나도 켜지지 않아 모든 폭에서
// 첫 단계(2열·3열)에 머문다. `ContentCardGrid` 는 그리드 바깥에 래퍼를 두고(그리드는 자기 폭을 질의할 수 없다),
// 홈 큐레이션 블록은 자기 섹션을 컨테이너로 둔다.
const SQUARE_COLUMNS = "grid-cols-2 @min-[37rem]:grid-cols-3 @min-[45rem]:grid-cols-4";

// `portrait`이 390px부터 3열인 이유(2026-09-11 갱신) — 예전엔 "패딩을
// 남기기로 해서 3열을 못 쓴다"였는데, 카드 껍데기(border+텍스트 영역 p-3)가 걷히며 그 전제가 사라졌다.
// 텍스트가 이제 카드 폭 전체를 쓴다: 고정비용(Eye 14 + gap 4 + `1,234` 34.8 + ` · ` 10.6 = 63.4px)을
// 뺀 나머지가 작가명 몫이고, 한글 1자 ≈ 12.1px @14px Pretendard(canvas 실측)다. 390:3열(카드 폭=텍스트
// 폭 111.33px, 작가명 47.9px=3.96자) · 640:4열(139px, 75.6px=6.2자) · 768:5열(134.4px, 71px=5.9자) ·
// 1024 좌측 패널 펼침:5열(그리드 736px, 카드 137.6px, 74.2px=6.1자) · 1024 레일:5열(172.8px, 109.4px=9.0자) ·
// 그리드가 상한 976px 에 닿는 폭:5열(185.6px, 122.2px=10자) — 전 구간에서 작가명이 최소 3.96자를 유지한다. **이 숫자를 다시
// 인용하기 전에 카드에 패딩이 없다는 전제부터 확인할 것** — 패딩이 돌아오면 3열은 다시 못 쓴다.
const PORTRAIT_COLUMNS = "grid-cols-3 @min-[37rem]:grid-cols-4 @min-[45rem]:grid-cols-5";

// `mixed`의 `items-start` — 없으면 grid 기본 `stretch`가 짧은 카드(캐릭터)를 긴 카드(스토리) 높이까지
// 늘려 **빈 border 상자**가 생긴다 — 두 타입의 썸네일 비율이 다른 한
// 이 결론은 유효하다. 실측 높이는 화면·뷰포트·`actions` 유무마다 달라 여기 숫자로 박아 두면 금방
// stale해진다 — 측정값이 필요하면 `DESIGN.md` §Cards의 화면·뷰포트가 라벨된 실측을 본다.
const MIXED_COLUMNS = "grid-cols-2 @min-[37rem]:grid-cols-3 @min-[45rem]:grid-cols-4 items-start";

const GRID_COLUMNS: Record<GridAspect, string> = {
  square: SQUARE_COLUMNS,
  portrait: PORTRAIT_COLUMNS,
  mixed: MIXED_COLUMNS,
};

/** 그리드 열 수는 타입별로 갈린다. `ContentCardGrid`가 이 함수 하나로
 * 열 클래스를 정한다. */
export function toGridColumns(aspect: GridAspect): string {
  return GRID_COLUMNS[aspect];
}
