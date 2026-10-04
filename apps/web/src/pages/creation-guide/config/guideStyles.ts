/**
 * 작성 가이드 화면이 여러 컴포넌트에서 같이 쓰는 클래스 묶음. 같은 요소가 페이지마다 다른 모양이 되지 않게 한곳에 둔다.
 */

/**
 * 누르면 다른 페이지로 가는 카드(개요의 단계 행, 단계 페이지의 이전/다음). 저장소의 클릭 카드 레시피(공지 목록과 같다)다 —
 * hover 면이 보이려면 바탕이 `card` 가 아니라 `background` 여야 하고, 포커스는 불투명 1px 보더가 3:1 을 진다.
 */
export const GUIDE_CLICK_CARD_CLASS =
  "rounded-xl border border-border bg-background outline-none motion-safe:transition-colors hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px";

/**
 * 목록·문장 속 칸 이름 링크(개요의 "AI가 읽는 때" 목록, 자주 하는 실수). 링크가 여럿 몰려도 유채색 덩어리가 되지 않게
 * 흐린 글자 + 글자색 밑줄로 둔다.
 *
 * 포커스를 `focus-visible:underline` 로 주지 않는 이유: 쉬는 상태에 이미 밑줄이 있어 바뀌는 것이 없다. 그래서 불투명 2px
 * 아웃라인이 3:1 을 진다. 스타일을 `focus-visible:outline-solid` 로 직접 적는다 — Tailwind 4 의 `outline-none` 은 아웃라인
 * 스타일 변수를 `none` 으로 세워, 이 클래스에 `outline-none` 이 붙으면 폭 유틸(`outline-2`)만으로는 선이 그려지지 않는다.
 */
export const GUIDE_QUIET_LINK_CLASS =
  "rounded-xs text-muted-foreground underline underline-offset-4 hover:text-foreground focus-visible:text-foreground focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring";

/**
 * 행 단위 접기 줄(`<summary>`). 폭을 `w-full` 로 두지 않는다 — `width:100%` 에 음수 좌우 마진을 주면 상자가 왼쪽으로만
 * 밀린다. 블록 수준 auto 폭이면 음수 마진만큼 양쪽으로 늘어나 hover 면과 포커스 링이 글자 양옆에 고르게 선다.
 * hover 면이 `secondary` 인 이유: `background` 위의 `muted` 는 거의 보이지 않는다.
 */
export const GUIDE_SUMMARY_CLASS =
  "-mx-2 flex min-h-9 cursor-pointer list-none items-center gap-2 rounded-lg border border-transparent px-2 text-sm font-medium text-foreground outline-none select-none hover:bg-secondary focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10 [&::-webkit-details-marker]:hidden";
