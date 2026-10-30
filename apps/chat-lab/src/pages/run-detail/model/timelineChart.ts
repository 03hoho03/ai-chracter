import type { StatSeries, TurnSummary } from "@/shared/api/client";

import { lineCandidates } from "./statLines";
import { SERIES_TONES } from "./turnRows";

export type LineTone = (typeof SERIES_TONES)[number];

/** 차트가 읽는 턴의 칸 — 턴 번호와, 그 턴의 시작 스탯이 바로 앞 번호 턴이 끝난 값과 같은가(측정 서버가 낸다). */
type TurnStart = Pick<TurnSummary, "turn" | "statsContinueFromPrevious">;

export type ChartLine = {
  id: string;
  name: string;
  tone: LineTone;
  /** 이 선의 데이터 키 둘. 끊긴 토막을 번갈아 실어, 차트가 토막과 토막 사이를 잇지 않게 한다. */
  keys: readonly [string, string];
  /** 턴 칸마다 값 — 그 턴의 값이 없으면 null. 툴팁과 고른 턴의 점이 읽는다. */
  values: ReadonlyArray<number | null>;
};

/** 차트의 한 칸(턴 하나). `index` 가 가로 자리이고 나머지 키는 선 토막의 값이다. */
export type ChartRow = Readonly<Record<string, number | null>>;

export type ChartModel = {
  rows: ChartRow[];
  lines: ChartLine[];
  domain: readonly [number, number];
  ticks: number[];
  /** 앞뒤 칸과 이어지지 않아 선분이 없는 점(`키:칸`) — 사라지지 않게 점으로 그린다. */
  isolated: ReadonlySet<string>;
};

export type EndLabel = { id: string; name: string; tone: LineTone; t: number; isShown: boolean };

export type StripTag = "hidden" | "unknown" | "recordOnly";

export type StatStrip = {
  id: string;
  name: string;
  tag: StripTag;
  /** 값이 바뀐 턴의 점. `t` 는 이 줄만의 세로 자리(0 아래 ~ 1 위)다. */
  dots: Array<{ index: number; value: number; t: number }>;
  /** 바뀐 값이 다음 변화(없으면 마지막 칸)까지 유지되는 구간. */
  holds: Array<{ from: number; to: number; t: number }>;
};

/** 끝 이름표 둘이 이만큼(차트 높이 비율)보다 가까우면 겹친다 — 12px 글자가 88px 차트에서 차지하는 몫쯤이다. */
const END_LABEL_GAP = 0.15;
const NICE_STEPS = [1, 2, 2.5, 5, 10] as const;

/**
 * 스탯 선 차트의 데이터. 가로 자리는 턴 번호가 아니라 칸 순번이다(번호가 건너뛰어도 칸은 같은 폭). 선은 두 경우에 끊는다 — 그
 * 턴의 값이 없을 때(없는 값을 0 이나 앞 값으로 잇지 않는다), 그리고 앞 칸에서 이 칸으로 가는 선분의 기울기가 이 턴의 변화량이
 * 아닐 때다. 뒤의 것은 앞 칸이 바로 앞 번호 턴이고 측정 서버가 이 턴의 시작 스탯이 그 턴이 끝난 값과 같다고 했을 때만 잇는다는
 * 뜻이다 — 시작 값을 모르거나(앞 턴 응답 교체·유실), 번호가 건너뛰었거나(사람이 친 구간), 기준을 다시 잡은 값이 다르면 끊는다. 그
 * 턴의 점은 남기고 들어오는 선분만 뺀다. 칸 수에 비례하는 한 번의 훑기로 만든다.
 */
export function buildChartModel(
  turns: ReadonlyArray<TurnStart>,
  series: ReadonlyArray<StatSeries>,
  slots: ReadonlyArray<string>,
): ChartModel {
  const indexOf = new Map(turns.map((summary, index) => [summary.turn, index]));
  const byId = new Map(lineCandidates(series).map((entry) => [entry.id, entry]));
  const rows: Array<Record<string, number | null>> = turns.map((_, index) => ({ index }));
  const isolated = new Set<string>();
  const lines: ChartLine[] = [];
  const shown: number[] = [];

  slots.forEach((id, slot) => {
    const entry = byId.get(id);
    const tone = SERIES_TONES[slot];
    if (entry === undefined || tone === undefined) return;
    const values: Array<number | null> = turns.map(() => null);
    for (const point of entry.points) {
      const index = indexOf.get(point.turn);
      if (index !== undefined) values[index] = point.value;
    }
    const keys = [`${id}:0`, `${id}:1`] as const;
    // 토막을 두 키에 번갈아 싣는다 — 한 키 안에서는 토막 사이에 빈 칸이 끼어 차트가 잇지 않는다.
    const keyOf = (order: number) => (order % 2 === 0 ? keys[0] : keys[1]);
    let run = -1;
    let runStart = 0;
    let runLast = 0;
    values.forEach((value, index) => {
      for (const key of keys) {
        const row = rows[index];
        if (row) row[key] = null;
      }
      if (value === null) return;
      shown.push(value);
      const current = turns[index];
      const continues =
        values[index - 1] != null &&
        current?.statsContinueFromPrevious === true &&
        turns[index - 1]?.turn === current.turn - 1;
      if (!continues) {
        if (run >= 0) markIfAlone(isolated, keyOf(run), runStart, runLast);
        run += 1;
        runStart = index;
      }
      runLast = index;
      const row = rows[index];
      if (row) row[keyOf(run)] = value;
    });
    if (run >= 0) markIfAlone(isolated, keyOf(run), runStart, runLast);
    lines.push({ id, name: entry.name, tone, keys, values });
  });

  const { domain, ticks } = niceScale(shown);
  return { rows, lines, domain, ticks, isolated };
}

/**
 * 세로 범위와 눈금. 값의 최소·최대를 1·2·2.5·5 × 10ⁿ 간격의 눈금으로 넓힌다(눈금 둘~넷 칸). 값이 하나뿐이면 그 값을 가운데
 * 둔다. 스탯의 정의상 최소·최대는 측정 기록에 없어 값으로만 잡는다.
 */
export function niceScale(values: ReadonlyArray<number>): { domain: [number, number]; ticks: number[] } {
  if (values.length === 0) return { domain: [0, 1], ticks: [] };
  let min = Infinity;
  let max = -Infinity;
  for (const value of values) {
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  if (min === max) {
    const pad = Math.max(1, Math.abs(min) * 0.1);
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / 2;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = (NICE_STEPS.find((multiple) => multiple * power >= raw) ?? 10) * power;
  const low = Math.floor(min / step) * step;
  const high = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let tick = low; tick <= high + step / 2; tick += step) ticks.push(Number(tick.toFixed(6)));
  return { domain: [Number(low.toFixed(6)), Number(high.toFixed(6))], ticks };
}

/**
 * 선 끝 이름표. 그 선이 마지막으로 값을 가진 칸의 높이에 두고, 높은 것부터 놓다가 이미 놓은 이름표와 겹치면 그 이름표만 숨긴다 —
 * 겹친 이름표를 위아래로 밀면 선에서 떨어져 엉뚱한 선을 가리킨다. 숨겨도 범례가 이름을 싣는다. 값이 없는 선은 이름표가 없다.
 */
export function placeEndLabels(lines: ReadonlyArray<ChartLine>, domain: readonly [number, number]): EndLabel[] {
  const labels = lines.flatMap((line) => {
    const last = [...line.values].reverse().find((value): value is number => value !== null);
    if (last === undefined) return [];
    return [{ id: line.id, name: line.name, tone: line.tone, t: normalize(last, domain), isShown: true }];
  });
  const placed: number[] = [];
  for (const label of [...labels].sort((a, b) => b.t - a.t)) {
    if (placed.some((t) => Math.abs(t - label.t) < END_LABEL_GAP)) label.isShown = false;
    else placed.push(label.t);
  }
  return labels;
}

/**
 * 본 차트 아래 따로 그리는 줄 — 선 후보가 아닌 계열(숨김 스탯, 숨김 여부를 모르는 스탯, 턴 기록에서만 온 보이는 스탯). 턴 기록에는
 * 바뀐 턴의 값만 있어 바뀐 턴에 점을 두고, 그 값이 다음 변화(없으면 마지막 칸)까지 유지되는 구간을 낸다. 세로 자리는 줄마다 따로
 * 잡는다(작은 다중) — 단위가 다를 수 있는 스탯을 본 차트의 축에 얹지 않는다.
 */
export function buildStrips(turns: ReadonlyArray<TurnStart>, series: ReadonlyArray<StatSeries>): StatStrip[] {
  const indexOf = new Map(turns.map((summary, index) => [summary.turn, index]));
  const candidates = new Set(lineCandidates(series));
  return series
    .filter((entry) => !candidates.has(entry))
    .map((entry) => {
      const placed = entry.points
        .flatMap((point) => {
          const index = indexOf.get(point.turn);
          return index === undefined ? [] : [{ index, value: point.value }];
        })
        .sort((a, b) => a.index - b.index);
      const scale = stripScale(placed.map((point) => point.value));
      const dots = placed.map((point) => ({ ...point, t: normalize(point.value, scale) }));
      const holds = dots.flatMap((dot, order) => {
        const to = dots[order + 1]?.index ?? turns.length - 1;
        return to > dot.index ? [{ from: dot.index, to, t: dot.t }] : [];
      });
      return { id: entry.id, name: entry.name, tag: stripTag(entry), dots, holds };
    });
}

/** 줄의 그 칸에서 유지되는 값 — 그 칸 이하에서 마지막으로 바뀐 값. 첫 변화 앞은 기록으로 모른다. */
export function heldValueAt(strip: StatStrip, index: number): number | undefined {
  let held: number | undefined;
  for (const dot of strip.dots) {
    if (dot.index > index) break;
    held = dot.value;
  }
  return held;
}

/** 따로 그리는 줄 묶음의 이름 — 모두 숨김 스탯이면 "숨김 스탯", 턴 기록에서만 온 보이는 스탯·숨김 여부 모름이 섞이면 넓은 이름. */
export function stripsLabel(strips: ReadonlyArray<StatStrip>): string {
  return strips.every((strip) => strip.tag === "hidden") ? "숨김 스탯" : "턴 기록 스탯";
}

function stripTag(entry: StatSeries): StripTag {
  if (entry.hidden === true) return "hidden";
  if (entry.hidden === null) return "unknown";
  return "recordOnly";
}

function stripScale(values: ReadonlyArray<number>): readonly [number, number] {
  if (values.length === 0) return [0, 1];
  return [Math.min(...values), Math.max(...values)];
}

/** 값의 세로 자리(0 아래 ~ 1 위). 범위가 0 이면 가운데. */
function normalize(value: number, [low, high]: readonly [number, number]): number {
  return high === low ? 0.5 : (value - low) / (high - low);
}

/** 토막(첫 칸 ~ 마지막 칸)이 한 칸뿐이면 그 점을 따로 그릴 점으로 둔다. */
function markIfAlone(isolated: Set<string>, key: string, first: number, last: number) {
  if (first === last) isolated.add(`${key}:${first}`);
}
