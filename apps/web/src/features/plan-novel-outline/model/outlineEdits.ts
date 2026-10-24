import type { NovelOutlineEpisodeInput, NovelOutlineView } from "@/entities/novel";

/** 양 끝 메시지(양 끝 포함)로 가리키는 대화 구간 — 구성안 화의 근거 한 칸. */
export type OutlineRange = { startMessageId: string; endMessageId: string };

/**
 * 근거를 보이고 나누는 단위인 턴. 담을 대화 단계와 같은 묶기(사용자 말 하나와 그 뒤 응답들, 방 맨 앞 응답은 혼자 한 턴)로 세어 두
 * 단계의 턴 번호가 같다. 호출부가 대화방 메시지 전부로 만들어 넘긴다.
 */
export type OutlineTurn = {
  key: string;
  number: number;
  messageIds: readonly string[];
  excerpt: string;
  /** 응답이 든 턴인가. 사용자 말 하나와 그 뒤 응답들이므로 참이면 턴의 마지막 메시지가 응답이다. */
  hasResponse: boolean;
};

/** 화면이 고치는 구성안 화 하나. */
export type OutlineEpisodeDraft = {
  /** 화면 안 열쇠 — 서버 화 키가 있으면 그 키, 나눠서 새로 생긴 화는 화면이 만든 값이다. */
  localId: string;
  /** 서버 화 키. 나눠서 새로 생긴 화는 없다(저장하면 서버가 새 키를 준다). */
  key: string | null;
  title: string;
  summary: string;
  goal: string;
  basis: OutlineRange[];
  /** 이 화로 쓴 원고. 있으면 근거와 글을 바꾸지 않는다. */
  chapterId: string | null;
};

export type OutlineEpisodeText = Pick<OutlineEpisodeDraft, "title" | "summary" | "goal">;

/** 줄거리·목표 길이 상한(서버 검증과 같은 값). 제목 상한은 상세의 `limits.chapterTitleMaxLength` 를 쓴다. */
export const OUTLINE_SUMMARY_MAX_LENGTH = 1000;
export const OUTLINE_GOAL_MAX_LENGTH = 300;
/** 한 화의 근거 구간 수 상한(서버 요청 검증과 같은 값). */
const OUTLINE_BASIS_MAX_COUNT = 50;
const DEFAULT_TITLE_MAX_LENGTH = 100;
const SPLIT_TITLE_SUFFIX = " (뒤)";

/** 턴 목록을 메시지 위치로 편 색인. 근거 구간을 턴으로 바꾸고 대화 차례로 정렬하는 데 쓴다. */
export type TurnIndex = {
  turns: readonly OutlineTurn[];
  /** 메시지 id → 방 처음부터 센 메시지 위치. */
  positionById: ReadonlyMap<string, number>;
  /** 메시지 위치 → 그 메시지가 든 턴의 차례(`turns` 의 위치). */
  turnAt: readonly number[];
  messageIds: readonly string[];
};

export function toTurnIndex(turns: readonly OutlineTurn[]): TurnIndex {
  const positionById = new Map<string, number>();
  const turnAt: number[] = [];
  const messageIds: string[] = [];
  turns.forEach((turn, turnIndex) => {
    for (const id of turn.messageIds) {
      positionById.set(id, messageIds.length);
      messageIds.push(id);
      turnAt.push(turnIndex);
    }
  });
  return { turns, positionById, turnAt, messageIds };
}

export function toEpisodeDrafts(view: NovelOutlineView): OutlineEpisodeDraft[] {
  return view.episodes.map((episode) => ({
    localId: episode.key,
    key: episode.key,
    title: episode.title,
    summary: episode.summary,
    goal: episode.goal,
    basis: episode.basis.map((range) => ({ startMessageId: range.startMessageId, endMessageId: range.endMessageId })),
    chapterId: episode.chapterId,
  }));
}

/** 고친 화 목록이 서버 판과 같은가(차례·글·근거·키). */
export function isSameAsView(episodes: readonly OutlineEpisodeDraft[], view: NovelOutlineView): boolean {
  if (episodes.length !== view.episodes.length) return false;
  return episodes.every((episode, index) => {
    const original = view.episodes[index];
    return (
      original !== undefined &&
      episode.key === original.key &&
      episode.title === original.title &&
      episode.summary === original.summary &&
      episode.goal === original.goal &&
      isSameBasis(episode.basis, original.basis)
    );
  });
}

function isSameBasis(a: readonly OutlineRange[], b: readonly OutlineRange[]): boolean {
  return (
    a.length === b.length &&
    a.every((range, index) => range.startMessageId === b[index]?.startMessageId && range.endMessageId === b[index]?.endMessageId)
  );
}

/** 근거 구간의 메시지 위치. 양 끝 중 하나라도 지금 대화에서 못 찾으면 `undefined` 다(그사이 지워졌다). */
function toPositions(index: TurnIndex, basis: readonly OutlineRange[]): [number, number][] | undefined {
  const positions: [number, number][] = [];
  for (const range of basis) {
    const start = index.positionById.get(range.startMessageId);
    const end = index.positionById.get(range.endMessageId);
    if (start === undefined || end === undefined || start > end) return undefined;
    positions.push([start, end]);
  }
  return positions;
}

/** 근거 구간이 덮는 턴(차례대로). 근거 메시지를 지금 대화에서 못 찾으면 `undefined` 다. */
export function toEpisodeTurns(index: TurnIndex, basis: readonly OutlineRange[]): OutlineTurn[] | undefined {
  const positions = toPositions(index, basis);
  if (positions === undefined) return undefined;
  const turnIndexes = new Set<number>();
  for (const [start, end] of positions) {
    for (let position = start; position <= end; position += 1) {
      const turnIndex = index.turnAt[position];
      if (turnIndex !== undefined) turnIndexes.add(turnIndex);
    }
  }
  return [...turnIndexes].sort((a, b) => a - b).flatMap((turnIndex) => index.turns[turnIndex] ?? []);
}

/** 근거 턴 이름 — 이어진 턴은 범위(`3~5턴`), 떨어진 묶음은 가운뎃점으로 잇는다(`1턴 · 3턴`). 못 찾으면 `undefined`. */
export function toBasisLabel(index: TurnIndex, basis: readonly OutlineRange[]): string | undefined {
  const turns = toEpisodeTurns(index, basis);
  if (turns === undefined || turns.length === 0) return undefined;
  const runs: [number, number][] = [];
  for (const turn of turns) {
    const last = runs.at(-1);
    if (last !== undefined && last[1] + 1 === turn.number) last[1] = turn.number;
    else runs.push([turn.number, turn.number]);
  }
  return runs.map(([first, last]) => (first === last ? `${first}턴` : `${first}~${last}턴`)).join(" · ");
}

/** 화를 나눌 수 있는 자리 — 화 안의 턴 사이 가운데 앞 턴이 응답으로 끝나는 곳. 서버는 근거가 응답에서 끝나고 응답 바로 뒤에서
 * 시작해야 받는다(턴 하나를 두 화로 가르지 않는다). 응답 없는 말 하나뿐인 턴 뒤는 그 말이 다음 응답과 한 턴이라 나눌 수 없다. */
export function toSplitPoints(
  index: TurnIndex,
  basis: readonly OutlineRange[],
): { afterTurnNumber: number; cutMessageId: string }[] {
  const positions = toPositions(index, basis);
  const turns = toEpisodeTurns(index, basis);
  if (positions === undefined || turns === undefined) return [];
  const lastPosition = positions.at(-1)?.[1] ?? -1;
  const inEpisode = (position: number) => positions.some(([start, end]) => start <= position && position <= end);
  return turns.flatMap((turn) => {
    const cutMessageId = turn.messageIds.at(-1);
    const cut = cutMessageId === undefined ? undefined : index.positionById.get(cutMessageId);
    if (!turn.hasResponse || cutMessageId === undefined || cut === undefined) return [];
    if (!inEpisode(cut) || cut >= lastPosition) return [];
    return [{ afterTurnNumber: turn.number, cutMessageId }];
  });
}

/** `localId` 화를 `cutMessageId` 뒤에서 둘로 나눈다. 앞 화는 그 메시지까지, 뒤 화는 그다음 메시지부터다 — 그 자리가 나눌 수 있는
 * 자리(`toSplitPoints`)가 아니면 `undefined`. 뒤 화는 키 없는 새 화이고 제목 뒤에 "(뒤)"를 붙이며 줄거리·목표는 그대로 둔다(이용자가
 * 곧 고친다). */
export function splitEpisode(
  episodes: readonly OutlineEpisodeDraft[],
  localId: string,
  cutMessageId: string,
  index: TurnIndex,
  newLocalId: string,
  limits: { titleMaxLength: number } = { titleMaxLength: DEFAULT_TITLE_MAX_LENGTH },
): OutlineEpisodeDraft[] | undefined {
  const at = episodes.findIndex((episode) => episode.localId === localId);
  const episode = episodes[at];
  if (episode === undefined || episode.chapterId !== null) return undefined;
  if (!toSplitPoints(index, episode.basis).some((point) => point.cutMessageId === cutMessageId)) return undefined;
  const cut = index.positionById.get(cutMessageId);
  const positions = toPositions(index, episode.basis);
  if (cut === undefined || positions === undefined) return undefined;

  const front: OutlineRange[] = [];
  const back: OutlineRange[] = [];
  positions.forEach(([start, end], rangeIndex) => {
    const range = episode.basis[rangeIndex];
    if (range === undefined) return;
    if (end <= cut) front.push(range);
    else if (start > cut) back.push(range);
    else {
      front.push({ startMessageId: range.startMessageId, endMessageId: cutMessageId });
      back.push({ startMessageId: index.messageIds[cut + 1] ?? "", endMessageId: range.endMessageId });
    }
  });
  const titleRoom = Math.max(0, limits.titleMaxLength - [...SPLIT_TITLE_SUFFIX].length);
  const backTitle = `${[...episode.title.trim()].slice(0, titleRoom).join("")}${SPLIT_TITLE_SUFFIX}`;
  return [
    ...episodes.slice(0, at),
    { ...episode, basis: front },
    { ...episode, localId: newLocalId, key: null, title: backTitle, basis: back },
    ...episodes.slice(at + 1),
  ];
}

/** `localId` 화를 바로 뒤 화와 합친다. 앞 화의 키·제목이 남고 줄거리·목표는 줄을 바꿔 잇는다(빈 목표는 빼고). 근거는 대화 차례로
 * 정렬한다 — 서버는 한 화의 근거가 대화 차례이기를 바란다(차례를 바꾼 뒤 합치면 뒤 화가 대화상 앞일 수 있다). 근거 구간끼리 붙여
 * 하나로 만들지 않는다: 붙어 보여도 담을 대화의 서로 다른 구간일 수 있다. 못 합치면 이유를 준다. */
export function mergeWithNext(
  episodes: readonly OutlineEpisodeDraft[],
  localId: string,
  index: TurnIndex | undefined,
): { episodes: OutlineEpisodeDraft[] } | { reason: string } {
  const at = episodes.findIndex((episode) => episode.localId === localId);
  const first = episodes[at];
  const second = episodes[at + 1];
  if (first === undefined || second === undefined) return { reason: "마지막 화라 합칠 다음 화가 없어요." };
  if (first.chapterId !== null || second.chapterId !== null) return { reason: "원고가 있는 화는 합칠 수 없어요." };
  if (index === undefined) return { reason: "대화를 불러온 뒤 합칠 수 있어요." };
  const basis = [...first.basis, ...second.basis];
  if (basis.length > OUTLINE_BASIS_MAX_COUNT) return { reason: "근거 구간이 많아 합칠 수 없어요." };
  const position = (range: OutlineRange) => index.positionById.get(range.startMessageId) ?? Number.MAX_SAFE_INTEGER;
  const merged: OutlineEpisodeDraft = {
    ...first,
    summary: joinText(first.summary, second.summary),
    goal: joinText(first.goal, second.goal),
    basis: basis.sort((a, b) => position(a) - position(b)),
  };
  return { episodes: [...episodes.slice(0, at), merged, ...episodes.slice(at + 2)] };
}

function joinText(a: string, b: string): string {
  return [a.trim(), b.trim()].filter((text) => text !== "").join("\n");
}

/** 화 하나를 한 칸 위(-1)·아래(1)로 옮기지 못하는 이유. 끝이거나, 원고가 있는 화와 자리를 바꾸게 되면 못 옮긴다 — 원고는 구성안
 * 차례대로 쓰므로 원고 있는 화의 앞뒤가 바뀌면 화 번호가 원고와 어긋난다. 옮길 수 있으면 `undefined`. */
export function toMoveBlockedReason(
  episodes: readonly OutlineEpisodeDraft[],
  localId: string,
  delta: -1 | 1,
): string | undefined {
  const at = episodes.findIndex((episode) => episode.localId === localId);
  const other = episodes[at + delta];
  if (at === -1 || other === undefined) return delta === -1 ? "맨 앞 화예요." : "맨 뒤 화예요.";
  if (episodes[at]?.chapterId !== null || other.chapterId !== null) return "원고가 있는 화와는 차례를 바꿀 수 없어요.";
  return undefined;
}

/** 화 하나를 한 칸 위(-1)·아래(1)로 옮긴다. 못 옮기는 자리(`toMoveBlockedReason`)면 그대로다. */
export function moveEpisode(episodes: readonly OutlineEpisodeDraft[], localId: string, delta: -1 | 1): OutlineEpisodeDraft[] {
  const at = episodes.findIndex((episode) => episode.localId === localId);
  const to = at + delta;
  const next = [...episodes];
  const moving = next[at];
  const other = next[to];
  if (moving === undefined || other === undefined || toMoveBlockedReason(episodes, localId, delta) !== undefined) return next;
  next[at] = other;
  next[to] = moving;
  return next;
}

/** 화 하나를 지운다. 구성안에는 화가 하나 이상 있어야 해 마지막 남은 화는 지우지 않는다. */
export function removeEpisode(episodes: readonly OutlineEpisodeDraft[], localId: string): OutlineEpisodeDraft[] {
  if (episodes.length <= 1) return [...episodes];
  return episodes.filter((episode) => episode.localId !== localId);
}

export function updateEpisodeText(
  episodes: readonly OutlineEpisodeDraft[],
  localId: string,
  text: OutlineEpisodeText,
): OutlineEpisodeDraft[] {
  return episodes.map((episode) => (episode.localId === localId ? { ...episode, ...text } : episode));
}

/** 저장 요청의 화 목록. 서버처럼 글의 앞뒤 공백을 걷는다. */
export function toSaveEpisodes(episodes: readonly OutlineEpisodeDraft[]): NovelOutlineEpisodeInput[] {
  return episodes.map((episode) => ({
    key: episode.key,
    title: episode.title.trim(),
    summary: episode.summary.trim(),
    goal: episode.goal.trim(),
    basis: episode.basis,
  }));
}

/** 서버가 그 칸을 재는 방식(앞뒤 공백을 뗀 코드 포인트 수). */
export function countOutlineChars(value: string): number {
  return [...value.trim()].length;
}

/** 저장하기 전에 고쳐야 할 것 — 화 번호를 붙인 문장들. 비었으면 저장할 수 있다. */
export function toOutlineProblems(
  episodes: readonly OutlineEpisodeDraft[],
  ordinals: readonly number[],
  limits: { titleMaxLength: number; maxEpisodes: number },
): string[] {
  if (episodes.length > limits.maxEpisodes) {
    return [`구성안은 ${limits.maxEpisodes.toLocaleString()}화까지예요. 화를 합치거나 지워주세요.`];
  }
  return episodes.flatMap((episode, index) => {
    const label = `${ordinals[index] ?? index + 1}화`;
    const problems: string[] = [];
    const titleLength = countOutlineChars(episode.title);
    if (titleLength === 0) problems.push(`${label} 제목을 적어주세요.`);
    else if (titleLength > limits.titleMaxLength) problems.push(`${label} 제목이 ${limits.titleMaxLength}자를 넘어요.`);
    const summaryLength = countOutlineChars(episode.summary);
    if (summaryLength === 0) problems.push(`${label} 줄거리를 적어주세요.`);
    else if (summaryLength > OUTLINE_SUMMARY_MAX_LENGTH) problems.push(`${label} 줄거리가 ${OUTLINE_SUMMARY_MAX_LENGTH}자를 넘어요.`);
    if (countOutlineChars(episode.goal) > OUTLINE_GOAL_MAX_LENGTH) problems.push(`${label} 목표가 ${OUTLINE_GOAL_MAX_LENGTH}자를 넘어요.`);
    return problems;
  });
}
