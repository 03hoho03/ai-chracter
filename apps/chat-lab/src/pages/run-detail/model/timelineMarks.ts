import type { TimelineMarker } from "@/shared/api/client";

import { MARKER_STYLES, type TimelineMarkKind } from "./detailLabels";

export type MarkerTone = (typeof MARKER_STYLES)[TimelineMarkKind]["tone"];

/** 표지 줄의 한 자리 — 같은 자리(같은 턴 칸, 또는 같은 턴 사이)에 놓이는 표지를 한 묶음으로. */
export type MarkerGroup = {
  key: string;
  /** 그 표지가 가리키는 턴의 칸 순번. 런에 없는 턴이면 -1. */
  index: number;
  isAfterTurn: boolean;
  /** 가로 자리(0~1). */
  position: number;
  glyphs: string;
  tone: MarkerTone;
  /** 자리와 표지 낱말·설명을 모두 이은 문장 — 마우스를 올리면·읽기 프로그램이 읽는다. */
  title: string;
};

/** 축 눈금을 몇 턴마다 둘지 — 칸이 좁아도 숫자끼리 겹치지 않을 만큼. */
const TICK_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500] as const;
const MAX_TICKS = 12;
const TONE_WEIGHT = { muted: 0, warn: 1, danger: 2 } as const satisfies Record<MarkerTone, number>;

/** 묶음을 만드는 동안 쥐는 것 — 표지마다 자리 낱말(`턴 N`·`턴 N 뒤`)과 표지 낱말. 제목은 다 모은 뒤 잇는다. */
type GroupDraft = Omit<MarkerGroup, "title"> & { entries: Array<{ where: string; label: string }> };

/**
 * 표지 줄에 놓을 묶음. 측정 서버의 표지에 턴 요약의 보충 줄 턴을 더한다. 턴 표지는 그 턴 칸 가운데, 드라이버 줄에서 온 표지
 * (rebase 등)는 그 턴 뒤라 그 턴과 다음 칸 사이 경계에 놓는다. 런 안쪽 번호 공백에 놓일 턴 뒤 표지(칸 1·2·5 의 턴 4 뒤 등 — 사람이
 * 친 구간 뒤 기준 다시 잡기)는 그 번호보다 큰 첫 칸의 앞 경계다. 런 밖 턴이면 가까운 쪽 끝이다. 같은 자리의 표지는 한 묶음으로
 * 모아 모양을 잇고(겹쳐 그리면 앞 모양이 가려진다) 색은 가장 무거운 것(실패 > 호박 > 흐림)을 따른다.
 *
 * 턴 뒤 묶음 바로 다음 칸에 턴 묶음이 있으면 둘을 한 묶음으로 합쳐 뒤 칸에 둔다 — 실패한 시도 → 기준 다시 잡기 → 같은 턴 재시도의
 * 순서라 실제 런에서 늘 반 칸 거리로 붙고, 칸이 좁으면 뒤 모양이 앞 모양을 덮어 앞 표지의 낱말에 끝내 닿지 못한다. 합치면 턴 사이
 * 자리는 모양으로는 사라지지만 제목이 "턴 N 뒤" 를 그대로 싣는다. 제목은 일어난 순서(턴 뒤 → 다음 턴)로 잇고, 첫 표지와 자리가
 * 다른 표지는 낱말 앞에 그 자리를 적는다.
 */
export function placeMarkers(
  turns: ReadonlyArray<number>,
  markers: ReadonlyArray<TimelineMarker>,
  supplementedTurns: ReadonlyArray<number>,
): MarkerGroup[] {
  const indexOf = new Map(turns.map((turn, index) => [turn, index]));
  const groups = new Map<string, GroupDraft>();
  const marks: Array<{ kind: TimelineMarkKind; turn: number; detail?: string | null }> = [
    ...markers,
    ...supplementedTurns.map((turn) => ({ kind: "supplemented" as const, turn, detail: null })),
  ];

  for (const mark of marks) {
    const style = MARKER_STYLES[mark.kind];
    const { index, position, key } = markSlot(turns, indexOf, mark.turn, style.isAfterTurn);
    const entry = {
      where: style.isAfterTurn ? `턴 ${mark.turn} 뒤` : `턴 ${mark.turn}`,
      label: mark.detail ? `${style.label} — ${mark.detail}` : style.label,
    };
    const existing = groups.get(key);
    if (existing === undefined) {
      groups.set(key, { key, index, isAfterTurn: style.isAfterTurn, position, glyphs: style.glyph, tone: style.tone, entries: [entry] });
      continue;
    }
    absorb(existing, { glyphs: style.glyph, tone: style.tone, entries: [entry] });
  }

  for (const draft of [...groups.values()]) {
    const next = draft.isAfterTurn ? groups.get(`at:${draft.index + 1}`) : undefined;
    if (draft.index === -1 || next === undefined) continue;
    groups.delete(draft.key);
    groups.set(next.key, { ...next, glyphs: draft.glyphs, tone: draft.tone, entries: [...draft.entries] });
    const merged = groups.get(next.key);
    if (merged) absorb(merged, next);
  }

  return [...groups.values()]
    .sort((a, b) => a.position - b.position)
    .map(({ entries, ...group }) => ({ ...group, title: groupTitle(entries) }));
}

/** 묶음에 다른 표지를 더한다 — 모양은 처음 보는 것만 잇고, 색은 더 무거운 쪽, 낱말은 뒤에. */
function absorb(target: GroupDraft, source: Pick<GroupDraft, "glyphs" | "tone" | "entries">) {
  for (const glyph of source.glyphs) if (!target.glyphs.includes(glyph)) target.glyphs += glyph;
  if (TONE_WEIGHT[source.tone] > TONE_WEIGHT[target.tone]) target.tone = source.tone;
  target.entries.push(...source.entries);
}

/** "첫 자리 · 낱말 · (다른 자리면 그 자리) 낱말 …". */
function groupTitle(entries: ReadonlyArray<{ where: string; label: string }>): string {
  const head = entries[0]?.where ?? "";
  return [head, ...entries.map((entry) => (entry.where === head ? entry.label : `${entry.where} ${entry.label}`))].join(" · ");
}

/** 눈금을 둘 턴 칸 — 처음·끝과, 칸 수에 맞춘 간격마다. */
export function tickIndexes(count: number): number[] {
  if (count === 0) return [];
  const step = tickStep(count);
  const indexes = new Set<number>([0, count - 1]);
  for (let index = step - 1; index < count - 1; index += step) {
    // 끝 눈금과 너무 붙으면 뺀다.
    if (count - 1 - index >= step / 2) indexes.add(index);
  }
  return [...indexes].sort((a, b) => a - b);
}

/**
 * 눈금 줄에 쓸 숫자. 고른 턴이 눈금이 아니면 그 턴 숫자를 더하고, 그 숫자와 반 간격 안에 있는 이웃 눈금은 그리지 않는다 — 간격은
 * 숫자끼리 겹치지 않게 고른 것이라 반 간격 안의 두 숫자는 겹칠 수 있다(끝과 너무 붙은 눈금을 빼는 규칙과 같은 기준).
 */
export function tickLabels(count: number, selectedIndex: number): Array<{ index: number; isSelected: boolean }> {
  const ticks = tickIndexes(count);
  // 고른 턴이 이미 눈금이면 이웃 눈금은 늘 반 간격 이상 떨어져 있어 지울 것이 없다 — 빠른 경로.
  if (selectedIndex < 0 || selectedIndex >= count || ticks.includes(selectedIndex)) {
    return ticks.map((index) => ({ index, isSelected: index === selectedIndex }));
  }
  const step = tickStep(count);
  return [...ticks.filter((index) => Math.abs(index - selectedIndex) >= step / 2), selectedIndex]
    .sort((a, b) => a - b)
    .map((index) => ({ index, isSelected: index === selectedIndex }));
}

/**
 * 띠 위 포인터가 가리키는 칸 순번. 표지 글리프 위면 그 묶음의 칸(턴 뒤 표지는 그 턴, 합친 묶음은 뒤 턴)이다 — 턴 뒤 표지는 칸
 * 경계에 있어 가로 자리로 고르면 다음 턴이 잡힌다. 그 밖(또는 묶음 칸이 런 밖)은 가로 비율의 칸.
 */
export function indexAtPointer(markerIndex: number | undefined, ratio: number, count: number): number | undefined {
  if (markerIndex !== undefined && markerIndex >= 0 && markerIndex < count) return markerIndex;
  return indexAtRatio(ratio, count);
}

/** 띠 안 가로 비율(0~1)이 가리키는 칸 순번. 양 끝 밖은 끝 칸이고, 칸이 없으면 undefined. */
export function indexAtRatio(ratio: number, count: number): number | undefined {
  if (count === 0) return undefined;
  return Math.min(count - 1, Math.max(0, Math.floor(ratio * count)));
}

/**
 * 표지 하나의 자리 — 칸 순번(묶음 열쇠·툴팁이 쓴다), 가로 자리, 묶음 열쇠. 턴 뒤 표지는 그 턴 칸 뒤 경계(`after:{칸}`)이고, 런 안쪽
 * 번호 공백이면 그 번호보다 큰 첫 칸 i 의 앞 경계(`after:{i-1}`)라 공백 앞 턴의 턴 뒤 표지와 같은 자리다. 런 밖이면 가까운 쪽 끝.
 */
function markSlot(
  turns: ReadonlyArray<number>,
  indexOf: ReadonlyMap<number, number>,
  turn: number,
  isAfterTurn: boolean,
): { index: number; position: number; key: string } {
  const count = turns.length;
  const inRun = indexOf.get(turn);
  if (inRun !== undefined) {
    return isAfterTurn
      ? { index: inRun, position: (inRun + 1) / count, key: `after:${inRun}` }
      : { index: inRun, position: (inRun + 0.5) / count, key: `at:${inRun}` };
  }
  const next = turns.findIndex((candidate) => candidate > turn);
  if (isAfterTurn && next > 0) return { index: next - 1, position: next / count, key: `after:${next - 1}` };
  const position = count === 0 || next === 0 ? 0 : 1;
  return { index: -1, position, key: `edge:${position}` };
}

/**
 * 눈금 간격(칸 수). 간격 수(칸 수 ÷ 간격)가 12 이하가 되는 가장 작은 값을 `TICK_STEPS` 에서 고르고(처음·끝 눈금을 더해 숫자는
 * 13개까지 선다), 가장 큰 500 으로도 12 를 넘으면(칸 6,000 초과) 칸 수 ÷ 12 를 올린 값이다.
 */
function tickStep(count: number): number {
  return TICK_STEPS.find((candidate) => count / candidate <= MAX_TICKS) ?? Math.ceil(count / MAX_TICKS);
}
