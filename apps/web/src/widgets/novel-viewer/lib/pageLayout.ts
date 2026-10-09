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
 * 바의 버튼만 한다). 화면 수를 아직 모르면(0) 첫 화면이다. */
export function clampScreen(screen: number, screenCount: number): number {
  return Math.max(Math.min(screen, screenCount - 1), 0);
}

/** 화면 `screen` 을 보일 때의 `scrollLeft`. */
export function toScrollLeft(screen: number, step: number): number {
  return screen * step;
}

/** 브라우저가 포커스·찾기 등으로 스크롤러를 화면 사이에 옮겨 놓았을 때 맞출 가장 가까운 화면. 화면 폭을 아직 모르면
 * (0) 첫 화면이다. */
export function toNearestScreen({
  scrollLeft,
  step,
  screenCount,
}: {
  scrollLeft: number;
  step: number;
  screenCount: number;
}): number {
  if (step <= 0) return 0;
  return clampScreen(Math.round(scrollLeft / step), screenCount);
}

/** 다단에서 잰 단 배치 — 화 끝 블록이 끝나는 단 번호와, 펼침에서 화 끝을 새 펼침 왼쪽으로 밀려고 켠 빈 단의 번호
 * (켜지 않았으면 없음). 둘 다 0부터. */
export type ColumnSpan = { lastColumnIndex: number; spacerColumnIndex: number | undefined };

/** 논리 쪽 수 — 판형 한 장이 한 쪽이고 화 끝 쪽도 센다. 펼침에서 켠 빈 단은 쪽이 아니다 — 세면 같은 화가 한 장으로
 * 볼 때보다 펼쳐 볼 때 한 쪽 많아진다. */
export function toPageCount({ lastColumnIndex, spacerColumnIndex }: ColumnSpan): number {
  return lastColumnIndex + 1 - (spacerColumnIndex === undefined ? 0 : 1);
}

/** 화면 `screen` 에 보이는 논리 쪽 번호(1부터). 펼침이면 둘이고, 빈 단이거나 화 끝 뒤라 쪽이 없는 자리는 뺀다. */
export function toVisiblePages({ screen, columnCount, ...span }: ColumnSpan & { screen: number; columnCount: 1 | 2 }): number[] {
  const pages: number[] = [];
  for (let column = screen * columnCount; column < (screen + 1) * columnCount; column += 1) {
    if (column > span.lastColumnIndex || column === span.spacerColumnIndex) continue;
    const isAfterSpacer = span.spacerColumnIndex !== undefined && column > span.spacerColumnIndex;
    pages.push(column + 1 - (isAfterSpacer ? 1 : 0));
  }
  return pages;
}

/** 화 안 위치의 쪽 표시 — 한 장 "3 / 16쪽", 펼침 "3–4 / 16쪽", 한 쪽만 보이는 펼침(화 끝·빈 단 옆) "16 / 16쪽". */
export function toPageLabel(input: ColumnSpan & { screen: number; columnCount: 1 | 2 }): string {
  const pages = toVisiblePages(input);
  const first = pages[0] ?? 1;
  const last = pages.at(-1) ?? first;
  const range = first === last ? `${first}` : `${first}–${last}`;
  return `${range} / ${toPageCount(input)}쪽`;
}
