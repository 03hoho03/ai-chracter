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

/**
 * 표지 줄에 놓을 묶음. 측정 서버의 표지에 턴 요약의 보충 줄 턴을 더한다. 턴 표지는 그 턴 칸 가운데, 드라이버 줄에서 온 표지
 * (rebase 등)는 그 턴 뒤라 그 턴과 다음 칸 사이 경계에 놓는다. 런 안쪽 번호 공백에 놓일 턴 뒤 표지(칸 1·2·5 의 턴 4 뒤 등 — 사람이
 * 친 구간 뒤 기준 다시 잡기)는 그 번호보다 큰 첫 칸의 앞 경계다. 런 밖 턴이면 가까운 쪽 끝이다. 같은 자리의 표지는 한 묶음으로
 * 모아 모양을 잇고(겹쳐 그리면 앞 모양이 가려진다) 색은 가장 무거운 것(실패 > 호박 > 흐림)을 따르며, 다른 턴에서 온 표지는 낱말
 * 앞에 그 턴을 적는다.
 */
export function placeMarkers(
  turns: ReadonlyArray<number>,
  markers: ReadonlyArray<TimelineMarker>,
  supplementedTurns: ReadonlyArray<number>,
): MarkerGroup[] {
  const indexOf = new Map(turns.map((turn, index) => [turn, index]));
  const groups = new Map<string, MarkerGroup & { where: string; entries: string[] }>();
  const marks: Array<{ kind: TimelineMarkKind; turn: number; detail?: string | null }> = [
    ...markers,
    ...supplementedTurns.map((turn) => ({ kind: "supplemented" as const, turn, detail: null })),
  ];

  for (const mark of marks) {
    const style = MARKER_STYLES[mark.kind];
    const { index, position, key } = markSlot(turns, indexOf, mark.turn, style.isAfterTurn);
    const where = style.isAfterTurn ? `턴 ${mark.turn} 뒤` : `턴 ${mark.turn}`;
    const label = mark.detail ? `${style.label} — ${mark.detail}` : style.label;
    const existing = groups.get(key);
    if (existing === undefined) {
      groups.set(key, {
        key,
        index,
        isAfterTurn: style.isAfterTurn,
        position,
        glyphs: style.glyph,
        tone: style.tone,
        title: where,
        where,
        entries: [label],
      });
      continue;
    }
    if (!existing.glyphs.includes(style.glyph)) existing.glyphs += style.glyph;
    if (TONE_WEIGHT[style.tone] > TONE_WEIGHT[existing.tone]) existing.tone = style.tone;
    existing.entries.push(where === existing.where ? label : `${where} ${label}`);
  }

  return [...groups.values()]
    .sort((a, b) => a.position - b.position)
    .map((group) => ({
      key: group.key,
      index: group.index,
      isAfterTurn: group.isAfterTurn,
      position: group.position,
      glyphs: group.glyphs,
      tone: group.tone,
      title: [group.title, ...group.entries].join(" · "),
    }));
}

/** 눈금을 둘 턴 칸 — 처음·끝과, 칸 수에 맞춘 간격마다. */
export function tickIndexes(count: number): number[] {
  if (count === 0) return [];
  const step = TICK_STEPS.find((candidate) => count / candidate <= MAX_TICKS) ?? Math.ceil(count / MAX_TICKS);
  const indexes = new Set<number>([0, count - 1]);
  for (let index = step - 1; index < count - 1; index += step) {
    // 끝 눈금과 너무 붙으면 뺀다.
    if (count - 1 - index >= step / 2) indexes.add(index);
  }
  return [...indexes].sort((a, b) => a - b);
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
