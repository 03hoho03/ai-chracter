// 메시지 본문 렌더러(chatMarkdown)와 한 줄 미리보기(stripChatNotation)가 함께 쓰는 표기 규칙.
// 두 곳이 같은 규칙을 각자 가지면 미리보기와 본문의 글자가 어긋나므로 규칙은 여기 한 곳에만 둔다.

export type StarNeighbor = "none" | "space" | "marker" | "other";
export type StarRun = { length: number; prev: StarNeighbor; next: StarNeighbor };
export type StarToken<T> = { kind: "run"; run: StarRun } | { kind: "content"; value: T };
export type WrapDepth = 1 | 2 | 3;
export type StarTree<T> = Array<
  { kind: "content"; value: T } | { kind: "literal"; length: number } | { kind: "wrap"; depth: WrapDepth; children: StarTree<T> }
>;
export type Fence = { char: string; length: number };
type LineStart = { prefix: string; body: string; hasListMarker: boolean; hasQuoteMarker: boolean };
type CloserTable = Record<WrapDepth, Int32Array>;

// 파서가 `\*` 를 글자 `*` 로 풀어 버리면 짝 없는 별표와 구별할 수 없다. 그래서 짝짓기 전에 사용자
// 입력에 나올 일이 없는 사용자 영역 문자로 바꿔 두고, 짝짓기가 끝난 뒤 되돌린다.
export const ESCAPED_STAR = "";
// 파서에게는 숨기고 별표 짝짓기에는 별표로 참여시키는 별표·밑줄(`hideDelimitersFromParser` 참고).
export const RAW_STAR = "";
export const RAW_UNDERSCORE = "";
const ESCAPED_STAR_PATTERN = /(?<!\\)((?:\\\\)*)\\\*/g;
const FENCE_OPEN_PATTERN = /^ {0,3}(`{3,}|~{3,})/;
const FENCE_CLOSE_PATTERN = /^ {0,3}(`{3,}|~{3,})\s*$/;
// 인용(`>` 뒤 공백 또는 줄 끝)과 목록 표지(`-`·`*`·`+`·`N.`·`N)` 뒤 공백). 여러 겹 중첩될 수 있다.
const CONTAINER_PREFIX_PATTERN = /^ {0,3}(?:>(?=\s|$)[ \t]?|([-*+]|\d{1,9}[.)])[ \t]+)/;
const DATE_LIKE_PATTERN = /^\s*\d{1,9}\.\s+\d{1,9}\./;
const STAR_RUN_PATTERN = /\*+/g;
// 인용·목록을 이보다 깊게 겹치면 나머지 표지는 글자로 둔다. 파서가 겹친 목록을 깊이의 제곱으로 느리게
// 읽고(4000겹에 2초) 렌더러는 깊이만큼 재귀해 스택이 넘친다. 채팅에서 이만큼 겹칠 일은 없다.
export const MAX_CONTAINER_DEPTH = 8;
// 별표 짝짓기가 만드는 강조의 중첩 한도. 짝 없는 여는 별표가 몇만 개 이어져도 재귀가 이 깊이에서 멈춘다.
// 더 깊은 표지는 지운다(지문 안의 지문은 겉보기가 같아 글자만 남기면 된다).
const MAX_STAR_NESTING = 8;

export function protectEscapedStars(text: string): string {
  return text.replace(ESCAPED_STAR_PATTERN, `$1${ESCAPED_STAR}`);
}

export function openFence(line: string): Fence | undefined {
  const marker = FENCE_OPEN_PATTERN.exec(line)?.[1];
  return marker ? { char: marker.charAt(0), length: marker.length } : undefined;
}

export function isFenceClose(line: string, fence: Fence): boolean {
  const marker = FENCE_CLOSE_PATTERN.exec(line)?.[1];
  return marker !== undefined && marker.charAt(0) === fence.char && marker.length >= fence.length;
}

/**
 * 줄을 컨테이너 표지(인용·목록, 여러 겹)와 그 뒤의 본문으로 가른다. 본문의 머리가 곧 채팅 규칙이 보는
 * "줄 머리"다 — `> 2026. 9. 29.` 의 날짜도 `- >_<` 의 이모티콘도 표지 뒤에서 판정해야 한다.
 * 날짜형 번호(`2026. 9. 29.`)는 목록 표지로 먹지 않고 본문으로 남긴다. 표지는 `MAX_CONTAINER_DEPTH`
 * 겹까지만 표지이고, 그 뒤의 표지는 본문(글자)이다.
 */
export function splitLineStart(line: string): LineStart {
  let prefix = "";
  let body = line;
  let hasListMarker = false;
  let hasQuoteMarker = false;
  for (let depth = 0; depth < MAX_CONTAINER_DEPTH && !DATE_LIKE_PATTERN.test(body); depth += 1) {
    const match = CONTAINER_PREFIX_PATTERN.exec(body);
    if (!match) break;
    if (match[1] !== undefined) hasListMarker = true;
    else hasQuoteMarker = true;
    prefix += match[0];
    body = body.slice(match[0].length);
  }
  return { prefix, body, hasListMarker, hasQuoteMarker };
}

export function isDateLike(body: string): boolean {
  return DATE_LIKE_PATTERN.test(body);
}

/** 본문이 컨테이너 표지로 시작하는지(= 깊이 한도를 넘어 글자로 남겨야 하는 표지인지). */
export function startsWithContainerMarker(body: string): boolean {
  return CONTAINER_PREFIX_PATTERN.test(body);
}

/** 텍스트를 별표 런(연속된 `*`)과 그 사이 글자로 나눈다. 텍스트 바깥 이웃은 호출부가 알려 준다. */
export function tokenizeStars(text: string, before: StarNeighbor, after: StarNeighbor): StarToken<string>[] {
  const tokens: StarToken<string>[] = [];
  let last = 0;
  for (const match of text.matchAll(STAR_RUN_PATTERN)) {
    const start = match.index;
    const end = start + match[0].length;
    if (start > last) tokens.push({ kind: "content", value: text.slice(last, start) });
    tokens.push({
      kind: "run",
      run: {
        length: match[0].length,
        prev: start > 0 ? classifyChar(text.charAt(start - 1)) : before,
        next: end < text.length ? classifyChar(text.charAt(end)) : after,
      },
    });
    last = end;
  }
  if (last < text.length) tokens.push({ kind: "content", value: text.slice(last) });
  return tokens;
}

export function classifyChar(char: string): StarNeighbor {
  if (char === "") return "none";
  return /\s/.test(char) ? "space" : "other";
}

/**
 * 파서가 짝짓지 못하고 글자로 남긴 별표 런을 다시 짝짓는다. 한국어는 글자와 구두점(`"`, `.`, `~`)이
 * 별표에 바로 붙어 CommonMark 의 flanking 규칙이 강조를 만들지 못하기 때문이다.
 * - 조건은 공백뿐이다: 여는 런은 "다음 글자가 공백이 아님", 닫는 런은 "앞 글자가 공백이 아님".
 *   뒤에 공백이 오는 런(`5* 줬다`)은 여는 표지가 될 수 없어 글자로 남는다.
 * - 같은 종류끼리 짝짓는다(1개 = 지문, 2개 = 굵게, 3개 = 굵은 지문). 네 개 이상은 파서처럼 짝수면
 *   굵게, 홀수면 굵은 지문이다 — 파서는 `****굵게****` 를 굵게 안의 굵게로 읽는다.
 * - 같은 종류의 닫는 런이 없으면 가장 가까운 다른 종류의 닫는 런에서 닫는다. 더 짧으면 스트리밍 중
 *   닫는 별표가 반만 도착한 모양(`**굵게*`)이고, 더 길면 남는 별표가 다음 강조를 연다
 *   (`**"왜?"***고개를 든다*` → 굵게 + 지문).
 * - 끝까지 닫히지 않은 여는 런은 문단 끝까지 감싼다 — 스트리밍 중 모양이 저장 후에도 그대로 남는다.
 * - 뒤에 아무것도 없는 런은 지운다(보여 줄 이유가 없는 반쪽 표지다).
 * 감싼 안쪽도 같은 규칙으로 다시 짝짓는다. 토큰 수에 비례하는 시간에 끝난다.
 */
export function pairStarRuns<T>(tokens: StarToken<T>[]): StarTree<T> {
  return pairRange(tokens, buildCloserTable(tokens), 0, tokens.length, 0);
}

export function toWrapDepth(length: number): WrapDepth | undefined {
  if (length < 1) return undefined;
  if (length === 1) return 1;
  return length % 2 === 0 ? 2 : 3;
}

function pairRange<T>(tokens: StarToken<T>[], closers: CloserTable, start: number, end: number, nesting: number): StarTree<T> {
  const tree: StarTree<T> = [];
  let index = start;
  // 더 긴 닫는 런에서 닫고 남은 별표. 닫는 런 자리에서 새 런처럼 이어서 처리한다.
  let carry: StarRun | undefined;
  while (carry || index < end) {
    let run: StarRun;
    if (carry) {
      run = carry;
      carry = undefined;
    } else {
      const token = tokens[index];
      index += 1;
      if (!token) break;
      if (token.kind === "content") {
        tree.push(token);
        continue;
      }
      run = token.run;
    }

    const depth = toWrapDepth(run.length);
    if (!depth || run.next === "space") {
      tree.push({ kind: "literal", length: run.length });
      continue;
    }
    if (run.next === "none" || run.next === "marker" || nesting >= MAX_STAR_NESTING) continue;

    const closeIndex = findCloser(closers, index, end, depth);
    const contentEnd = closeIndex === -1 ? end : closeIndex;
    tree.push({ kind: "wrap", depth, children: pairRange(tokens, closers, index, contentEnd, nesting + 1) });
    index = contentEnd + 1;

    const closer = tokens[closeIndex];
    if (closer?.kind === "run" && closer.run.length > run.length) {
      carry = { length: closer.run.length - run.length, prev: "marker", next: closer.run.next };
    }
  }
  return tree;
}

/** 강조 종류마다 "i 이후 처음 나오는 닫을 수 있는 런"의 위치를 미리 구해 둔다(없으면 -1). */
function buildCloserTable<T>(tokens: StarToken<T>[]): CloserTable {
  const size = tokens.length + 1;
  const table: CloserTable = { 1: new Int32Array(size).fill(-1), 2: new Int32Array(size).fill(-1), 3: new Int32Array(size).fill(-1) };
  for (let index = tokens.length - 1; index >= 0; index -= 1) {
    for (const length of [1, 2, 3] as const) table[length][index] = table[length][index + 1] ?? -1;
    const token = tokens[index];
    const length = token?.kind === "run" ? toWrapDepth(token.run.length) : undefined;
    if (token?.kind === "run" && length && canClose(token.run)) table[length][index] = index;
  }
  return table;
}

function findCloser(closers: CloserTable, from: number, end: number, length: WrapDepth): number {
  const within = (index: number | undefined) => (index !== undefined && index !== -1 && index < end ? index : -1);
  const exact = within(closers[length][from]);
  if (exact !== -1) return exact;
  const others = ([1, 2, 3] as const).filter((other) => other !== length).map((other) => within(closers[other][from]));
  const found = others.filter((index) => index !== -1);
  return found.length > 0 ? Math.min(...found) : -1;
}

// 문단 끝의 런은 앞이 공백이어도 닫는다(`*웃는다 *`).
function canClose(run: StarRun): boolean {
  return run.next === "none" || run.prev === "other" || run.prev === "marker";
}
