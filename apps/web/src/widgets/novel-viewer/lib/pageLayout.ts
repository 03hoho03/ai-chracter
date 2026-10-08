/** 두 쪽을 펼치는 최소 창 폭. 이보다 좁거나 세로로 긴 화면을 둘로 나누면 쪽마다 한 줄이 너무 짧아져 한 쪽이 낫다. */
const SPREAD_MIN_WIDTH_PX = 1024;

/** 정밀 포인터(마우스·트랙패드) 기기에서 쪽 좌우에 비워 두는 넘김 버튼 자리(한쪽) — 바깥 8 + 버튼 40 + 안쪽 8.
 * 쪽 폭을 계산하기 전에 먼저 빼서 버튼이 어떤 창 폭에서도 글자를 가리지 않게 한다. 터치 기기는 버튼이 바와 함께만
 * 나타나므로 이 자리를 쓰지 않는다. */
const PAGE_BUTTON_GUTTER_PX = 56;

/** 쪽 위·아래 여백(safe-area 별도). 스크롤 모드 본문의 위 여백과 같은 값이라 모드를 바꿔도 첫 줄 높이가 같다. */
const PAGE_VERTICAL_PADDING_PX = 40;

/** 두 쪽 펼침 여부. 폭과 높이가 같은 정사각 창은 가로로 친다 — CSS `orientation: landscape` 는 같은 값을 세로로
 * 쳐서 이 판정을 미디어쿼리 대신 잰 크기로 한다. */
export function toColumnCount({ width, height }: { width: number; height: number }): 1 | 2 {
  return width >= SPREAD_MIN_WIDTH_PX && width >= height ? 2 : 1;
}

export type PageLayoutInput = {
  /** 페이지 본문 상자(뷰포트를 채우는 고정 상자)의 크기(px). */
  width: number;
  height: number;
  safeArea: { left: number; right: number; top: number; bottom: number };
  isFinePointer: boolean;
  /** 쪽 안쪽 좌우 여백 한쪽(px) — 보기 설정의 여백 단계가 만든 패딩을 잰 값. */
  pagePaddingPx: number;
  /** 지금 글자 크기에서 잰 `max-w-prose`(65ch)의 px 폭. 글꼴이 도착하면 달라지므로 그때도 다시 잰다. */
  proseWidthPx: number;
  lineHeightPx: number;
};

export type PageGeometry = {
  columnCount: 1 | 2;
  /** 글자가 놓이는 단 폭(정수 px). */
  columnWidth: number;
  /** 단 사이 간격 = 쪽 안쪽 좌우 여백의 합. 펼침 두 쪽 사이 간격도 이 값이다. */
  columnGap: number;
  /** 한 화면 폭 = 스크롤러 폭 = 한 번 넘길 때 움직이는 `scrollLeft`(정수 px). */
  step: number;
  /** 단 높이 — 줄 높이의 정수배로 내려 맞춘 값. */
  columnHeight: number;
  /** 스크롤러를 놓을 자리(본문 상자 기준 px). */
  left: number;
  top: number;
};

/**
 * 창 크기와 보기 설정에서 쪽 기하를 구한다. 폭은 전부 정수 px 다 — 소수 폭이면 `scrollLeft` 가 정수로 반올림돼
 * 넘길수록 단 위치가 어긋나고 마지막 화면에 닿지 못한다. 쪽 상자(글자 + 좌우 여백)의 상한을 `max-w-prose` 로 두는
 * 것은 스크롤 모드 본문 상자와 같은 꼴이라, 넓은 화면에서 모드를 바꿔도 한 줄 글자 수가 같게 하려는 것이다. 단
 * 높이를 줄 높이의 배수로 내리는 것은 단 아래에 반 줄이 잘려 보이는 엔진(WebKit 보고)을 대비해서다. 아주 낮은
 * 창에서도 한 줄은 남긴다 — 높이 0 인 단에는 글자가 놓일 자리가 없다.
 */
export function toPageGeometry({
  width,
  height,
  safeArea,
  isFinePointer,
  pagePaddingPx,
  proseWidthPx,
  lineHeightPx,
}: PageLayoutInput): PageGeometry {
  const columnCount = toColumnCount({ width, height });
  const gutter = isFinePointer ? PAGE_BUTTON_GUTTER_PX : 0;
  const columnGap = 2 * pagePaddingPx;
  const available = width - safeArea.left - safeArea.right - 2 * gutter;
  const columnWidth = Math.min(Math.floor(available / columnCount), Math.floor(proseWidthPx)) - columnGap;
  const step = columnCount * (columnWidth + columnGap);
  const top = PAGE_VERTICAL_PADDING_PX + safeArea.top;
  const bottom = PAGE_VERTICAL_PADDING_PX + safeArea.bottom;
  const lineCount = Math.max(1, Math.floor((height - top - bottom) / lineHeightPx));

  return {
    columnCount,
    columnWidth,
    columnGap,
    step,
    columnHeight: lineCount * lineHeightPx,
    left: safeArea.left + gutter + Math.floor((available - step) / 2),
    top,
  };
}

/** 화면 수 — 화 끝 블록이 끝나는 단 번호(0부터)로 센다. 펼침이면 두 단이 한 화면이다. */
export function toScreenCount({
  lastColumnIndex,
  columnCount,
}: {
  lastColumnIndex: number;
  columnCount: 1 | 2;
}): number {
  return Math.floor(lastColumnIndex / columnCount) + 1;
}

/** 화면 번호를 `0 … 화면 수 - 1` 로 자른다. 첫 화면 앞이나 화 끝 화면 뒤로는 넘어가지 않는다(다른 화로 가는 것은
 * 바의 버튼만 한다). */
export function clampScreen(screen: number, screenCount: number): number {
  return Math.min(Math.max(screen, 0), screenCount - 1);
}

/** 화면 `screen` 을 보일 때의 `scrollLeft`. */
export function toScrollLeft(screen: number, step: number): number {
  return screen * step;
}

/** 브라우저가 포커스·찾기 등으로 스크롤러를 화면 사이에 옮겨 놓았을 때 맞출 가장 가까운 화면. */
export function toNearestScreen({
  scrollLeft,
  step,
  screenCount,
}: {
  scrollLeft: number;
  step: number;
  screenCount: number;
}): number {
  return clampScreen(Math.round(scrollLeft / step), screenCount);
}
