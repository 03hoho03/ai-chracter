import { PAGE_FORMAT_HEIGHT_PX, PAGE_FORMAT_WIDTH_PX } from "./pageFormat";

/** 위·아래 바 한 줄의 높이(px). 바 컴포넌트가 이 값으로 줄 높이를 정하고, 판형 배율 계산은 그 자리(+ 경계선 1px +
 * safe-area)를 늘 비운다 — 값을 두 군데 적으면 바와 판형이 겹치거나 틈이 생긴다. rem 이 아니라 px 인 이유는 판형
 * 자리 계산이 px 이라서다(브라우저 기본 글자 크기가 바 높이를 바꾸면 바가 판형을 덮는다). */
export const VIEWER_BAR_ROW_PX = 56;
/** 바 한쪽이 차지하는 자리(safe-area 제외) — 줄 + 본문과 가르는 경계선 1px. */
export const VIEWER_BAR_SPACE_PX = VIEWER_BAR_ROW_PX + 1;

/** 마우스·트랙패드 기기에서 판형 좌우에 비워 두는 넘김 버튼 자리(한쪽) — 바깥 8 + 버튼 40 + 안쪽 8. 배율을 구하기
 * 전에 가용 폭에서 먼저 빼 버튼이 어떤 창에서도 판형을 가리지 않게 한다. 판형 크기에는 들어가지 않아 포인터 종류가
 * 쪽 수를 바꾸지 않는다. */
const PAGE_BUTTON_GUTTER_PX = 56;

/** 배율 상한 — 본문 설정 최대 20px 이 24px(`text-2xl`, 이 시스템의 크기 천장)에 닿는 값. 넘는 화면에서는 판형 둘레가
 * 빈다. */
export const PAGE_SCALE_MAX = 1.2;
/** 배율 하한 — 기본 글자 16px 이 12.8px 이 되는 값. 이보다 작으면 읽을 수 없어 그 기기에서는 스크롤 모드로 보인다. */
export const PAGE_SCALE_MIN = 0.8;
/** 하한 밑에서 페이지 모드로 돌아오는 배율 — 하한보다 조금 높다. 창 가장자리를 끌어 크기를 바꾸는 중처럼 배율이
 * 하한 근처에서 오가면 모드가 그때마다 바뀌어 본문이 갈아 끼워지고 안내가 다시 뜬다. 하한과 이 값 사이에서는 지금
 * 모드를 지킨다. 이 값보다 높이면 iPhone SE 의 Safari 세로(바 자리를 뺀 높이 439px → 0.813)가 가로로 눕혔다 다시
 * 세워도 스크롤 모드에 남는다. 띠가 판형 높이로 5px 남짓이라, 모바일 주소창이 접히고 펴지는 차이(수십 px)로 오가는
 * 것까지는 막지 못한다. */
export const PAGE_SCALE_RESUME = 0.81;

export type SafeArea = { top: number; right: number; bottom: number; left: number };

export type PageFitInput = {
  /** 창(레이아웃 뷰포트) 크기(px). */
  viewportWidth: number;
  viewportHeight: number;
  safeArea: SafeArea;
  isFinePointer: boolean;
  /** 직전 배치가 하한 밑이었나 — 그러면 하한이 아니라 `PAGE_SCALE_RESUME` 이상이어야 하한 밑을 벗어난다. */
  wasBelowMinimum: boolean;
};

export type PageFit = {
  /** 한 화면에 놓는 판형 수 — 펼침이면 2. */
  columnCount: 1 | 2;
  /** 판형 배율. 반올림하지 않는다 — 화면 좌표를 판형 좌표로 되돌릴 때 반올림한 배율을 쓰면 단 경계 근처의 글자가
   * 앞 단으로 잘못 분류된다. */
  scale: number;
  /** 배율이 하한 밑이다(직전에 하한 밑이었으면 `PAGE_SCALE_RESUME` 밑) — 이 기기에서는 페이지 모드를 쓰지 않는다. */
  isBelowMinimum: boolean;
  /** 판형 묶음(펼침이면 두 장)이 놓이는 화면 사각형(px). 위치는 정수로 내려 놓는다. */
  left: number;
  top: number;
  width: number;
  height: number;
};

/**
 * 창에 판형을 맞춘다. 위·아래 바 자리는 바가 숨어 있어도 늘 비운다 — 바를 여닫아도 판형이 1px 도 움직이지 않게
 * 하려는 것이라 입력에 바 표시 여부가 없다.
 *
 * 펼침은 펼쳐도 배율이 줄지 않을 때만 한다(상한에 걸린 넓은 화면, 또는 높이가 배율을 정하는 가로 화면). 배율이
 * 하한 밑이면 값을 자르지 않고 그대로 낸 채 `isBelowMinimum` 으로 알린다 — 하한으로 고정하면 판형이 바 자리나 창을
 * 넘친다.
 */
export function toPageFit({ viewportWidth, viewportHeight, safeArea, isFinePointer, wasBelowMinimum }: PageFitInput): PageFit {
  const gutter = isFinePointer ? PAGE_BUTTON_GUTTER_PX : 0;
  const barSpace = VIEWER_BAR_SPACE_PX;
  const availableWidth = Math.max(0, viewportWidth - safeArea.left - safeArea.right - 2 * gutter);
  const availableHeight = Math.max(0, viewportHeight - (barSpace + safeArea.top) - (barSpace + safeArea.bottom));
  const heightScale = availableHeight / PAGE_FORMAT_HEIGHT_PX;
  const singleScale = Math.min(availableWidth / PAGE_FORMAT_WIDTH_PX, heightScale, PAGE_SCALE_MAX);
  const spreadScale = Math.min(availableWidth / (2 * PAGE_FORMAT_WIDTH_PX), heightScale, PAGE_SCALE_MAX);
  const columnCount = spreadScale >= singleScale ? 2 : 1;
  const scale = columnCount === 2 ? spreadScale : singleScale;
  const width = columnCount * PAGE_FORMAT_WIDTH_PX * scale;
  const height = PAGE_FORMAT_HEIGHT_PX * scale;

  return {
    columnCount,
    scale,
    isBelowMinimum: scale < (wasBelowMinimum ? PAGE_SCALE_RESUME : PAGE_SCALE_MIN),
    left: Math.floor(safeArea.left + gutter + (availableWidth - width) / 2),
    top: Math.floor(barSpace + safeArea.top + (availableHeight - height) / 2),
    width,
    height,
  };
}

/** 같은 화면 배치인가 — 창 크기 변화가 배치를 바꾸지 않았으면 다시 그리지 않는다. */
export function isSamePageFit(a: PageFit | undefined, b: PageFit | undefined): boolean {
  if (a === undefined || b === undefined) return a === b;
  return (
    a.columnCount === b.columnCount &&
    a.scale === b.scale &&
    a.left === b.left &&
    a.top === b.top &&
    a.width === b.width &&
    a.height === b.height
  );
}
