import { cn } from "@ai-character-chat/ui/lib/utils";

/**
 * 좌측 패널의 행(내비·최근 대화)이 함께 쓰는 상태 레시피. 행 모양(높이·패딩)은 각 행이 더한다.
 *
 * - 정지 글자는 `muted-foreground` 다. 패널은 화면 높이 내내 보이는 면이라 행 열여섯 개를 밝기 천장(`foreground`)으로
 *   두면 그만큼 밝은 글자가 늘 켜진다 — 현재 항목 하나만 천장으로 올라가 "비활성에서 활성으로 밝기가 오른다".
 * - hover·현재 채움은 `secondary` 이고 글자도 `foreground` 로 올린다. 라이트에서 `muted-foreground` 는 `secondary` 위
 *   4.30:1 로 본문 기준에 못 미친다(DESIGN.md Colors 절 표면 위 채움).
 * - 현재 항목(`aria-current="page"`)은 채움·굵기에 더해 왼쪽 1px `foreground` 막대(위아래 8px 띄움)를 둔다. 채움은
 *   배경 대비 3:1 에 못 미치고, 굵기는 라벨이 숨는 레일에서 사라지며, 글자색 차이는 다크에서 3:1 미달이라 두 상태 모두에서
 *   남는 단서가 따로 있어야 한다. 막대는 1px 무채색이라 사이드 보더 금지(1px 를 넘는 유색 옆줄)에 들지 않는다.
 * - 포커스는 보더 없는 컨트롤 레시피(불투명 1px 아웃라인 + 50% 링). `outline-none` 을 함께 두면 아웃라인 스타일 변수가
 *   none 으로 남아 포커스 때 아웃라인이 사라지므로 쓰지 않는다.
 * - 손가락 포인터에서는 40px 로 올린다(마우스 데스크톱의 밀도는 그대로).
 */
export const SIDE_PANEL_ROW_CLASS = cn(
  "relative flex items-center gap-3 rounded-lg text-sm font-medium whitespace-nowrap text-muted-foreground",
  "motion-safe:transition-colors hover:bg-secondary hover:text-foreground",
  "focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring",
  "pointer-coarse:min-h-10",
  "aria-[current=page]:bg-secondary aria-[current=page]:text-foreground",
  "aria-[current=page]:before:absolute aria-[current=page]:before:inset-y-2 aria-[current=page]:before:left-0 aria-[current=page]:before:w-px aria-[current=page]:before:bg-foreground",
);

/** 글자가 보이는 내비 행(펼친 패널·드로어). 드로어도 같은 클래스를 써야 같은 목적지가 두 표면에서 같은 hover·현재 표시를
 * 갖는다. 현재 항목의 굵기는 이 행에만 건다 — 라벨이 숨는 레일 칸에서는 굵기가 보이지 않는다.
 *
 * `shrink-0`: 드로어는 이 행 몇 개(알림 펼침·로그아웃·비로그인 로그인)를 스크롤하는 세로 flex 에 바로 놓는다. 높이가
 * `h-9` 고정에 세로 패딩이 없어, 내용이 넘치면 flex 아이템의 자동 최소 높이(글자 한 줄)까지 줄어든다. `<li>` 안에 놓인
 * 행은 flex 아이템이 아니라 영향이 없다. */
export const SIDE_PANEL_NAV_ROW_CLASS = cn(
  SIDE_PANEL_ROW_CLASS,
  "h-9 shrink-0 px-4 [&_svg]:size-4 [&_svg]:shrink-0 aria-[current=page]:font-semibold",
);
