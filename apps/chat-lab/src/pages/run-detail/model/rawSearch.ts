/** 원문 안 일치 하나의 자리(`end` 는 포함하지 않는다). */
export type TextMatch = {
  start: number;
  end: number;
};

export type TextSegment = {
  text: string;
  kind: "plain" | "match" | "current";
};

const REGEXP_SPECIAL = /[.*+?^${}()|[\]\\]/g;

/**
 * 원문에서 검색어가 나오는 자리 — 대소문자를 가리지 않고, 겹치는 일치는 앞에서부터 하나씩만 센다. 소문자로 바꾼 사본에서 찾지
 * 않는 것은, 바꾸면 길이가 달라지는 글자가 있어 사본의 자리가 원문의 자리와 어긋나기 때문이다.
 */
export function findMatches(text: string, query: string): TextMatch[] {
  if (query.trim() === "") return [];
  const pattern = new RegExp(query.replace(REGEXP_SPECIAL, "\\$&"), "giu");
  return Array.from(text.matchAll(pattern), (match) => ({ start: match.index, end: match.index + match[0].length }));
}

/** 다음(1)·이전(-1) 일치. 끝에서 처음으로 돈다. 아직 고른 일치가 없으면(-1) 다음은 첫 일치, 이전은 마지막 일치. 일치가 없으면 -1. */
export function stepMatch(current: number, count: number, step: 1 | -1): number {
  if (count === 0) return -1;
  if (current < 0) return step === 1 ? 0 : count - 1;
  return (current + step + count) % count;
}

/** 원문을 일치 사이 글과 일치로 나눈다. `currentIndex` 번째 일치는 `current` 다. */
export function splitByMatches(text: string, matches: ReadonlyArray<TextMatch>, currentIndex: number): TextSegment[] {
  const segments: TextSegment[] = [];
  let cursor = 0;
  matches.forEach((match, index) => {
    if (match.start > cursor) segments.push({ text: text.slice(cursor, match.start), kind: "plain" });
    segments.push({ text: text.slice(match.start, match.end), kind: index === currentIndex ? "current" : "match" });
    cursor = match.end;
  });
  if (cursor < text.length || segments.length === 0) segments.push({ text: text.slice(cursor), kind: "plain" });
  return segments;
}
