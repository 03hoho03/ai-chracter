/** 고친 문단의 연속 범위. 서버가 나눈 문단 인덱스(0부터)이고 양 끝을 포함한다 — AI 수정 요청의
 * `paragraphStart`·`paragraphEnd` 와 같은 뜻이다. */
export type ParagraphRange = { start: number; end: number };

/** 문단 하나를 눌렀을 때의 다음 범위. 범위는 언제나 이어진 문단이다(떨어진 문단 두 개를 따로 고를 수 없다).
 *
 * - 고른 것이 없으면 그 문단 하나.
 * - 범위 밖을 누르면 그 문단까지 늘린다 — 바로 옆이면 한 칸, 떨어져 있으면 사이 문단을 모두 넣는다.
 * - 범위 안을 누르면 그 문단 하나로 다시 시작한다. 범위가 그 문단 하나뿐이면 고른 것을 푼다.
 * - `extend`(Shift+클릭·Shift+Enter)는 언제나 늘리는 쪽이다: 밖이면 위와 같고, 안이면 시작은 두고 끝을 그 문단으로
 *   옮긴다(줄이기). 다시 시작하거나 풀지 않는다.
 *
 * 그래서 누르기만으로도, Tab 으로 옮겨 Enter 만 쳐도 같은 범위를 만들 수 있다. */
export function nextParagraphRange(
  range: ParagraphRange | null,
  index: number,
  { extend = false }: { extend?: boolean } = {},
): ParagraphRange | null {
  if (range === null) return { start: index, end: index };
  const isInside = index >= range.start && index <= range.end;
  if (!isInside) return { start: Math.min(range.start, index), end: Math.max(range.end, index) };
  if (extend) return { start: range.start, end: index };
  if (range.start === index && range.end === index) return null;
  return { start: index, end: index };
}

/** 본문이 바뀌어(다른 곳의 수정을 다시 받음) 문단 수가 줄었을 때 범위를 남은 문단 안으로 접는다. 문단이 없으면
 * 범위도 없다. */
export function clampParagraphRange(range: ParagraphRange | null, paragraphCount: number): ParagraphRange | null {
  if (range === null || paragraphCount === 0) return null;
  const last = paragraphCount - 1;
  return { start: Math.min(range.start, last), end: Math.min(range.end, last) };
}

export function isParagraphInRange(range: ParagraphRange | null, index: number): boolean {
  return range !== null && index >= range.start && index <= range.end;
}

/** "3~5번째 문단" / "3번째 문단". 화면 번호는 1부터다. */
export function formatParagraphRange(range: ParagraphRange): string {
  const start = range.start + 1;
  const end = range.end + 1;
  return start === end ? `${start}번째 문단` : `${start}~${end}번째 문단`;
}

/** 고른 범위를 알리는 한 줄(`aria-live`). 고른 것이 없으면 빈 문장 대신 무엇을 하면 되는지 말한다. */
export function toParagraphSelectionAnnouncement(range: ParagraphRange | null): string {
  return range === null ? "고른 문단이 없어요." : `${formatParagraphRange(range)}을 골랐어요.`;
}
