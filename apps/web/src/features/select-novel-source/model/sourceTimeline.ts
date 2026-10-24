import { stripChatNotation } from "@/entities/chat-room";

/** 대화방 메시지 중 구간 고르기가 읽는 칸. 정렬은 서버의 방 메시지 순서(`created_at`, `id`)와 같다 — 구간 선택의 관문이 같은
 * 순서로 읽는다. */
export type SourceMessage = { id: string; role: "user" | "assistant"; content: string };

/** 양 끝 메시지(양 끝 포함)로 가리키는 대화 구간. */
export type SourceRange = { startMessageId: string; endMessageId: string };

/** 저장된 구간 하나(조회 응답). */
export type SourceSection = SourceRange & { mode: "include" | "context" };

/**
 * 고르는 단위인 턴 — 사용자 말 하나와 그 뒤 응답들. 방 맨 앞의 사용자 말 없는 응답(첫 인사)은 혼자 한 턴이다.
 *
 * 서버는 메시지 단위 끝을 받지만 구성안이 화를 나눌 때 턴을 가르지 못하게 막는다. 고르기를 턴으로 하면 그 규칙을 화면이 먼저
 * 지킨다.
 */
export type SourceTurn = {
  /** 첫 메시지 id. 다시 받아도 같은 턴을 가리키는 열쇠다. */
  key: string;
  /** 방 처음부터 센 턴 번호(1부터). */
  number: number;
  messageIds: string[];
  /** 두 줄로 보일 발췌 — 응답 글(없으면 사용자 말)에서 채팅 표기를 지운 것. */
  excerpt: string;
  /** 응답이 하나라도 든 턴인가. 담은 턴 중 이런 턴이 하나는 있어야 저장된다. */
  hasResponse: boolean;
  /** 이미 화가 된 대화에 걸친 턴. 담을 수 없고(맥락으로는 보낼 수 있다), 빼기로 세지 않는다. */
  isLocked: boolean;
  /** 고른 때의 고정 끝 뒤에 이어진 대화. "새 구간 추가"로 열기 전에는 고르지 않는다. */
  isNew: boolean;
};

/** 턴 하나의 상태. 잠긴 턴은 `locked` 이거나(맥락으로 보냈으면) `context` 다. */
export type TurnState = "include" | "context" | "exclude" | "locked";

export type TimelineSegment = { state: TurnState; turns: SourceTurn[] };

const EXCERPT_MAX = 200;

type BuildOptions = {
  /** 이 선택이 다루는 방의 마지막 메시지(고정 끝). 이 뒤는 새 대화다. */
  fixedEndId: string | null;
  /** 화면이 본 지금 방 끝. 이 뒤에 온 메시지는 다음 조회까지 다루지 않는다. */
  roomEndId: string | null;
  lockedRanges: readonly SourceRange[];
};

/** 메시지를 턴으로 묶는다. 고정 끝에 걸친 턴은 고정 끝에서 나눈다 — 고정 끝 뒤 메시지는 그 선택에 담을 수 없어서다.
 * 고정 끝을 메시지 목록에서 찾지 못하면(그사이 지워졌으면) 새 대화 없이 방 끝까지 다룬다. */
export function buildSourceTurns(messages: readonly SourceMessage[], options: BuildOptions): SourceTurn[] {
  const indexById = new Map(messages.map((message, index) => [message.id, index]));
  const roomEndIndex = options.roomEndId === null ? -1 : (indexById.get(options.roomEndId) ?? messages.length - 1);
  const fixedEndIndex = options.fixedEndId === null ? roomEndIndex : (indexById.get(options.fixedEndId) ?? roomEndIndex);
  const lockedIndexRanges = toIndexRanges(options.lockedRanges, indexById, roomEndIndex);

  const turns: SourceTurn[] = [];
  let current: SourceMessage[] = [];
  let currentIsNew = false;
  let currentStart = 0;
  const close = () => {
    if (current.length === 0) return;
    const end = currentStart + current.length - 1;
    turns.push(toTurn(current, turns.length + 1, currentIsNew, overlapsAny([currentStart, end], lockedIndexRanges)));
    current = [];
  };
  messages.slice(0, roomEndIndex + 1).forEach((message, index) => {
    const isNew = index > fixedEndIndex;
    if (current.length > 0 && (message.role === "user" || isNew !== currentIsNew)) close();
    if (current.length === 0) {
      currentStart = index;
      currentIsNew = isNew;
    }
    current.push(message);
  });
  close();
  return turns;
}

function toTurn(messages: SourceMessage[], number: number, isNew: boolean, isLocked: boolean): SourceTurn {
  const response = messages.find((message) => message.role === "assistant");
  const text = stripChatNotation((response ?? messages[0])?.content ?? "").trim();
  return {
    key: messages[0]?.id ?? "",
    number,
    messageIds: messages.map((message) => message.id),
    excerpt: text.length > EXCERPT_MAX ? `${text.slice(0, EXCERPT_MAX)}…` : text,
    hasResponse: response !== undefined,
    isLocked,
    isNew,
  };
}

type IndexRange = [number, number];

/**
 * 구간들(키 순)을 메시지 위치로 편다. 저장된 구간의 끝 메시지가 지금 대화에 없을 수 있다 — 마지막 답을 다시 만들면 그 답은 새
 * id 로 다시 쓰이고, 메시지를 고치거나 지우면 사라진다. 그 구간을 버리면 담았던 대화가 통째로 빼기로 보이고, 이용자가 모른 채
 * 승인하면 그대로 빠진다. 그래서 찾지 못한 끝은 이웃까지 넓힌다: 끝이 없으면 다음 구간 시작 바로 앞(없으면 `lastIndex`)까지,
 * 시작이 없으면 앞 구간 끝 바로 뒤(없으면 처음)부터다. 양 끝이 다 없으면 자리를 알 수 없어 그 구간은 어느 턴도 덮지 않는다.
 * 저장된 선택 구간이면 원문이 바뀐 구간이라 서버가 바뀜 표시를 함께 준다.
 */
function toIndexRanges(
  ranges: readonly SourceRange[],
  indexById: ReadonlyMap<string, number>,
  lastIndex: number,
): IndexRange[] {
  const found = ranges.map((range) => ({
    start: indexById.get(range.startMessageId),
    end: indexById.get(range.endMessageId),
  }));
  const resolved: IndexRange[] = [];
  found.forEach(({ start, end }, index) => {
    if (start === undefined && end === undefined) return;
    const previousEnd = resolved.at(-1)?.[1];
    const nextStart = found.slice(index + 1).find((item) => item.start !== undefined)?.start;
    const from = start ?? (previousEnd === undefined ? 0 : previousEnd + 1);
    const to = end ?? (nextStart === undefined ? lastIndex : nextStart - 1);
    if (from <= to) resolved.push([from, to]);
  });
  return resolved;
}

function overlapsAny([start, end]: IndexRange, ranges: readonly IndexRange[]): boolean {
  return ranges.some(([rangeStart, rangeEnd]) => start <= rangeEnd && rangeStart <= end);
}

/** 턴마다 메시지 위치 범위. 턴들이 같은 목록에서 나왔으므로 턴 순서대로 이어 센다. `lastOldIndex` 는 고정 끝(새 턴 앞)의 마지막
 * 메시지 위치다 — 저장된 구간은 그 뒤로 넘지 않는다. */
function turnIndexRanges(turns: readonly SourceTurn[]): {
  indexById: Map<string, number>;
  ranges: IndexRange[];
  lastOldIndex: number;
} {
  const indexById = new Map<string, number>();
  const ranges: IndexRange[] = [];
  let next = 0;
  let lastOldIndex = -1;
  for (const turn of turns) {
    ranges.push([next, next + turn.messageIds.length - 1]);
    for (const id of turn.messageIds) indexById.set(id, next++);
    if (!turn.isNew) lastOldIndex = next - 1;
  }
  return { indexById, ranges, lastOldIndex };
}

/** 저장된 판(또는 제안)을 턴 상태로 편다. 구간이 턴 가운데서 시작하거나 끝나도 그 턴을 덮는다 — 담기가 맥락보다 앞선다.
 * 잠긴 턴은 맥락이 아니면 잠김이다(담기 구간에 들었어도 담지 않는다 — 서버가 거절한다). 고정 끝 뒤 새 턴은 담기로 둔다:
 * "새 구간 추가"로 열면 새로 이어진 대화를 담은 채 보인다. */
export function toBaseStates(turns: readonly SourceTurn[], sections: readonly SourceSection[]): Map<string, TurnState> {
  const { indexById, ranges, lastOldIndex } = turnIndexRanges(turns);
  // 끝을 찾지 못한 구간을 이웃까지 넓히려면 mode 와 상관없이 모든 구간의 차례를 함께 봐야 한다.
  const resolved = toIndexRanges(sections, indexById, lastOldIndex);
  const includeRanges = resolved.filter((_, index) => sections[index]?.mode === "include");
  const contextRanges = resolved.filter((_, index) => sections[index]?.mode === "context");
  return new Map(
    turns.map((turn, index): [string, TurnState] => {
      const range = ranges[index] ?? [0, -1];
      if (turn.isNew) return [turn.key, "include"];
      const inContext = overlapsAny(range, contextRanges);
      if (turn.isLocked) return [turn.key, inContext ? "context" : "locked"];
      if (overlapsAny(range, includeRanges)) return [turn.key, "include"];
      return [turn.key, inContext ? "context" : "exclude"];
    }),
  );
}

/** 구간들이 덮는 턴 가운데 담기가 아닌 턴을 담기로 바꾼다(잠긴 턴은 건너뛴다). 낡은 구성안의 근거 구간을 다시 담을 때 쓴다 —
 * 지금 대화에서 찾지 못한 구간은 자리를 알 수 없어 건너뛴다(끝을 이웃까지 넓히는 저장된 구간과 달리, 근거 구간은 저장된 선택이
 * 아니라 넓힐 이웃이 없다). `count` 는 바꾼 턴 수다. */
export function includeTurnsInRanges(
  turns: readonly SourceTurn[],
  states: ReadonlyMap<string, TurnState>,
  ranges: readonly SourceRange[],
): { states: Map<string, TurnState>; count: number } {
  const { indexById, ranges: turnRanges } = turnIndexRanges(turns);
  const wanted: IndexRange[] = [];
  for (const range of ranges) {
    const start = indexById.get(range.startMessageId);
    const end = indexById.get(range.endMessageId);
    if (start !== undefined && end !== undefined && start <= end) wanted.push([start, end]);
  }
  const next = new Map(states);
  let count = 0;
  turns.forEach((turn, index) => {
    if (turn.isLocked || !overlapsAny(turnRanges[index] ?? [0, -1], wanted)) return;
    if (stateOf(states, turn) === "include") return;
    next.set(turn.key, "include");
    count += 1;
  });
  return { states: next, count };
}

/** 저장 뒤 원문이 바뀐 구간이 덮는 턴. */
export function toChangedTurnKeys(
  turns: readonly SourceTurn[],
  sections: readonly (SourceRange & { sourceChanged: boolean })[],
): Set<string> {
  const { indexById, ranges, lastOldIndex } = turnIndexRanges(turns);
  const resolved = toIndexRanges(sections, indexById, lastOldIndex);
  const changed = resolved.filter((_, index) => sections[index]?.sourceChanged === true);
  return new Set(turns.filter((_, index) => overlapsAny(ranges[index] ?? [0, -1], changed)).map((turn) => turn.key));
}

function stateOf(states: ReadonlyMap<string, TurnState>, turn: SourceTurn): TurnState {
  return states.get(turn.key) ?? (turn.isLocked ? "locked" : "exclude");
}

/** 잠긴 턴에 상태를 맞춘다 — 잠긴 턴은 담기가 될 수 없고, 빼기는 잠김이다. */
function fitToLock(turn: SourceTurn, target: TurnState): TurnState {
  if (!turn.isLocked) return target === "locked" ? "exclude" : target;
  return target === "context" ? "context" : "locked";
}

/** 턴 하나를 누른 결과. 담기 ↔ 빼기이고 맥락은 누르면 담기다. 잠긴 턴은 맥락이었으면 잠김으로 돌아갈 뿐이다. */
export function toggleTurn(states: ReadonlyMap<string, TurnState>, turn: SourceTurn): Map<string, TurnState> {
  const current = stateOf(states, turn);
  const next = current === "include" ? "exclude" : "include";
  return new Map(states).set(turn.key, fitToLock(turn, next));
}

/** 두 턴 사이(양 끝 포함, 순서 무관)를 모두 담기나 빼기로 둔다. 잠긴 턴은 건너뛴다. */
export function setTurnRange(
  states: ReadonlyMap<string, TurnState>,
  turns: readonly SourceTurn[],
  fromKey: string,
  toKey: string,
  target: "include" | "exclude",
): Map<string, TurnState> {
  const from = turns.findIndex((turn) => turn.key === fromKey);
  const to = turns.findIndex((turn) => turn.key === toKey);
  const next = new Map(states);
  if (from === -1 || to === -1) return next;
  for (const turn of turns.slice(Math.min(from, to), Math.max(from, to) + 1)) {
    if (!turn.isLocked) next.set(turn.key, target);
  }
  return next;
}

/** 여러 턴(뺀 대화 묶음이나 맥락 묶음)을 한꺼번에 맥락이나 빼기로 둔다. 잠긴 턴의 빼기는 잠김이다. */
export function setTurnsState(
  states: ReadonlyMap<string, TurnState>,
  turns: readonly SourceTurn[],
  keys: readonly string[],
  target: "context" | "exclude",
): Map<string, TurnState> {
  const wanted = new Set(keys);
  const next = new Map(states);
  for (const turn of turns) {
    if (wanted.has(turn.key)) next.set(turn.key, fitToLock(turn, target));
  }
  return next;
}

/** 저장할 구간. 맞닿은 같은 상태(담기·맥락)의 턴은 한 구간이고, 상태가 바뀌거나 빼기·잠김이 끼면 끊는다. 잠긴 턴은 담기로
 * 보내지 않는다. 구간은 키 순이고 서로 메시지를 나누지 않는다. */
export function toSaveSections(turns: readonly SourceTurn[], states: ReadonlyMap<string, TurnState>): SourceSection[] {
  const sections: SourceSection[] = [];
  let open: { mode: "include" | "context"; start: string; end: string } | undefined;
  for (const turn of turns) {
    const state = fitToLock(turn, stateOf(states, turn));
    const mode = state === "include" || state === "context" ? state : undefined;
    const first = turn.messageIds[0];
    const last = turn.messageIds.at(-1);
    if (open !== undefined && open.mode !== mode) {
      sections.push({ mode: open.mode, startMessageId: open.start, endMessageId: open.end });
      open = undefined;
    }
    if (mode === undefined || first === undefined || last === undefined) continue;
    if (open === undefined) open = { mode, start: first, end: last };
    else open.end = last;
  }
  if (open !== undefined) sections.push({ mode: open.mode, startMessageId: open.start, endMessageId: open.end });
  return sections;
}

/** 응답이 든 턴을 하나라도 담았는가 — 서버가 그런 구간 없이는 저장하지 않는다. */
export function hasIncludedResponse(turns: readonly SourceTurn[], states: ReadonlyMap<string, TurnState>): boolean {
  return turns.some((turn) => turn.hasResponse && fitToLock(turn, stateOf(states, turn)) === "include");
}

export function countTurnStates(
  turns: readonly SourceTurn[],
  states: ReadonlyMap<string, TurnState>,
): Record<TurnState, number> {
  const counts: Record<TurnState, number> = { include: 0, context: 0, exclude: 0, locked: 0 };
  for (const turn of turns) counts[fitToLock(turn, stateOf(states, turn))] += 1;
  return counts;
}

/** 맞닿은 같은 상태의 턴을 한 묶음으로 — 타임라인이 묶음마다 머리(잠김 한 줄, 뺀 대화·맥락의 동의 버튼)를 단다. */
export function toTimelineSegments(turns: readonly SourceTurn[], states: ReadonlyMap<string, TurnState>): TimelineSegment[] {
  const segments: TimelineSegment[] = [];
  for (const turn of turns) {
    const state = fitToLock(turn, stateOf(states, turn));
    const last = segments.at(-1);
    if (last !== undefined && last.state === state) last.turns.push(turn);
    else segments.push({ state, turns: [turn] });
  }
  return segments;
}

/** 두 상태 지도가 이 턴들에서 같은가. */
export function isSameStates(
  turns: readonly SourceTurn[],
  a: ReadonlyMap<string, TurnState>,
  b: ReadonlyMap<string, TurnState>,
): boolean {
  return turns.every((turn) => fitToLock(turn, stateOf(a, turn)) === fitToLock(turn, stateOf(b, turn)));
}

/** 턴 번호 범위 이름(`6~9턴`, `4턴`). */
export function toTurnRangeLabel(turns: readonly SourceTurn[]): string {
  const first = turns[0]?.number;
  const last = turns.at(-1)?.number;
  if (first === undefined || last === undefined) return "";
  return first === last ? `${first}턴` : `${first}~${last}턴`;
}
