import {
  memo,
  useId,
  useMemo,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
} from "react";

import type { StatSeries, TimelineMarker, TurnSummary } from "@/shared/api/client";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/formatNumber";

import { lineCandidates, MAX_LINES } from "../model/statLines";
import {
  buildChartModel,
  buildStrips,
  heldValueAt,
  placeEndLabels,
  stripsLabel,
  type ChartLine,
  type ChartModel,
  type LineTone,
  type StatStrip,
  type StripTag,
} from "../model/timelineChart";
import { indexAtRatio, placeMarkers, tickIndexes, type MarkerGroup, type MarkerTone } from "../model/timelineMarks";
import { formatDeltaValue } from "../model/turnRows";
import { StatChart } from "./StatChart";

type StateTimelineProps = {
  /** 런의 턴 요약(서버 순서). 번호가 건너뛰어도 칸은 턴마다 같은 폭이다. */
  turns: ReadonlyArray<TurnSummary>;
  turnNumbers: ReadonlyArray<number>;
  series: ReadonlyArray<StatSeries>;
  markers: ReadonlyArray<TimelineMarker>;
  /** 선 자리마다 선 스탯 id — 자리 k 가 선 색 k 다. 턴 목록의 Δ 점도 같은 자리를 따른다. */
  slots: ReadonlyArray<string>;
  selectedTurn: number | undefined;
  timelineRef: RefObject<HTMLDivElement | null>;
  onSelectTurn: (turn: number) => void;
  onPickSlot: (slot: number, id: string) => void;
};

const MARKER_TONE_CLASSES = {
  muted: "text-ink-muted",
  warn: "text-warn",
  danger: "text-danger",
} as const satisfies Record<MarkerTone, string>;

const LINE_KEY_CLASSES = {
  "series-1": "bg-series-1",
  "series-2": "bg-series-2",
  "series-3": "bg-series-3",
} as const satisfies Record<LineTone, string>;

const STRIP_TAG_LABELS = {
  hidden: "숨김",
  unknown: "숨김 여부 모름",
  recordOnly: "턴 기록에서만",
} as const satisfies Record<StripTag, string>;

/**
 * 상태 타임라인 띠 — 위에서부터 범례(선 고르기·숨김 스탯 펼치기) · 표지 줄 · 스탯 선 차트 · 턴 눈금, 펼치면 숨김 스탯 줄. 높이는
 * 데이터와 상관없이 고정이고(펼침만 늘린다), 가로 자리는 턴 칸 순번이라 표지·선·눈금·고른 턴 띠가 세로로 맞는다.
 *
 * 띠를 누르면 가장 가까운 턴을 고르고, 포커스(`g`)가 있을 때 ←/→ 로 턴을 옮긴다. 마우스를 올리거나 키보드로 포커스하면 그 턴의
 * 모든 스탯 값·변화량·표지를 툴팁 하나에 보인다. 차트는 메모해 두어 턴을 옮기거나 마우스를 움직일 때 겹쳐 그리는 층만 다시 그린다.
 */
export function StateTimeline({
  turns,
  turnNumbers,
  series,
  markers,
  slots,
  selectedTurn,
  timelineRef,
  onSelectTurn,
  onPickSlot,
}: StateTimelineProps) {
  const chart = useMemo(() => buildChartModel(turns, series, slots), [turns, series, slots]);
  const endLabels = useMemo(() => placeEndLabels(chart.lines, chart.domain), [chart]);
  const strips = useMemo(() => buildStrips(turns, series), [turns, series]);
  const candidates = useMemo(() => lineCandidates(series), [series]);
  const markerGroups = useMemo(
    () =>
      placeMarkers(
        turnNumbers,
        markers,
        turns.filter((summary) => summary.supplemented).map((summary) => summary.turn),
      ),
    [turnNumbers, markers, turns],
  );
  const [hoverIndex, setHoverIndex] = useState<number | undefined>(undefined);
  const [isKeyboardFocused, setIsKeyboardFocused] = useState(false);
  const [isStripsOpen, setIsStripsOpen] = useState(false);
  const descriptionId = useId();

  const count = turnNumbers.length;
  const selectedIndex = selectedTurn === undefined ? -1 : turnNumbers.indexOf(selectedTurn);
  const readoutIndex = hoverIndex ?? (isKeyboardFocused && selectedIndex !== -1 ? selectedIndex : undefined);

  function indexAt(event: MouseEvent<HTMLDivElement>): number | undefined {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return undefined;
    return indexAtRatio((event.clientX - rect.left) / rect.width, count);
  }

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    const index = indexAt(event);
    const turn = index === undefined ? undefined : turnNumbers[index];
    if (turn !== undefined) onSelectTurn(turn);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = turnNumbers[Math.min(count - 1, Math.max(0, (selectedIndex === -1 ? 0 : selectedIndex) + step))];
    if (next !== undefined) onSelectTurn(next);
  }

  function handleFocus(event: FocusEvent<HTMLDivElement>) {
    // 마우스로 누른 포커스에는 툴팁을 남기지 않는다 — 키보드로 온 포커스(`g`·Tab)만 고른 턴의 값을 띄운다.
    setIsKeyboardFocused(event.currentTarget.matches(":focus-visible"));
  }

  return (
    <section aria-label="상태 타임라인" className="shrink-0 border-b border-border bg-surface px-3 py-1.5">
      <TimelineLegend
        lines={chart.lines}
        candidates={candidates}
        strips={strips}
        isStripsOpen={isStripsOpen}
        onToggleStrips={() => setIsStripsOpen((previous) => !previous)}
        onPickSlot={onPickSlot}
      />
      <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] md:grid-cols-[2rem_minmax(0,1fr)_5.5rem]">
        <YTicks chart={chart} />
        <div
          ref={timelineRef}
          tabIndex={0}
          role="group"
          aria-label={`턴 ${selectedTurn ?? "-"} / ${count} — 누르면 그 턴, ←/→ 로 옮긴다`}
          aria-describedby={descriptionId}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          onMouseMove={(event) => setHoverIndex(indexAt(event))}
          onMouseLeave={() => setHoverIndex(undefined)}
          onFocus={handleFocus}
          onBlur={() => setIsKeyboardFocused(false)}
          className="relative cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          {selectedIndex !== -1 && <SelectedBand index={selectedIndex} count={count} />}
          {hoverIndex !== undefined && (
            <span
              aria-hidden="true"
              // 십자선 — 마우스가 가리키는 턴 칸 가운데에 붙는다. 자리는 턴 수에 따라 달라지는 실행 중 값이다.
              style={{ left: `${((hoverIndex + 0.5) / count) * 100}%` }}
              className="pointer-events-none absolute inset-y-0 w-px bg-border-strong"
            />
          )}
          <MarkerRow groups={markerGroups} />
          <div className="relative h-14 md:h-22">
            <GridLines chart={chart} />
            {chart.lines.length === 0 ? (
              <p className="absolute inset-0 flex items-center justify-center text-data text-ink-muted">
                스탯 선 없음 — 드라이버 줄의 방 상태에 보이는 스탯 값이 없다
              </p>
            ) : (
              <div aria-hidden="true" className="absolute inset-0">
                <StatChart rows={chart.rows} lines={chart.lines} domain={chart.domain} isolated={chart.isolated} count={count} />
              </div>
            )}
            <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 inset-y-1">
              {selectedIndex !== -1 && <TurnDots chart={chart} index={selectedIndex} count={count} />}
              {hoverIndex !== undefined && hoverIndex !== selectedIndex && (
                <TurnDots chart={chart} index={hoverIndex} count={count} />
              )}
            </div>
          </div>
          <TickRow turnNumbers={turnNumbers} selectedIndex={selectedIndex} />
          {isStripsOpen && <StripTracks strips={strips} count={count} selectedIndex={selectedIndex} />}
          {readoutIndex !== undefined && (
            <Readout
              index={readoutIndex}
              count={count}
              summary={turns[readoutIndex]}
              chart={chart}
              strips={isStripsOpen ? strips : []}
              groups={markerGroups}
            />
          )}
          <p id={descriptionId} className="sr-only">
            {selectedIndex === -1 ? "고른 턴 없음" : describeTurn(chart, turns[selectedIndex], selectedIndex)}
          </p>
        </div>
        <EndLabels chart={chart} labels={endLabels} strips={isStripsOpen ? strips : []} />
      </div>
    </section>
  );
}

type TimelineLegendProps = {
  lines: ReadonlyArray<ChartLine>;
  candidates: ReadonlyArray<StatSeries>;
  strips: ReadonlyArray<StatStrip>;
  isStripsOpen: boolean;
  onToggleStrips: () => void;
  onPickSlot: (slot: number, id: string) => void;
};

/**
 * 범례 한 줄. 선마다 짧은 선 견본 + 스탯 이름이고, 선 후보가 셋보다 많으면 이름 자리가 고르기 칸이 된다(자리의 색은 그대로, 그
 * 자리에 설 스탯만 바뀐다). 오른쪽에 숨김 스탯 줄 펼치기 — 기본은 접힘이다.
 */
function TimelineLegend({ lines, candidates, strips, isStripsOpen, onToggleStrips, onPickSlot }: TimelineLegendProps) {
  const isPickable = candidates.length > MAX_LINES;
  return (
    <div className="flex h-5 items-center gap-3 text-label text-ink-secondary">
      <ul aria-label="스탯 선" className="flex min-w-0 items-center gap-3">
        {lines.map((line, slot) => (
          // 자리 순번이 그 자리의 정체다(색이 자리를 따른다) — 자리는 늘거나 순서가 바뀌지 않는다.
          <li key={slot} className="flex min-w-0 items-center gap-1.5">
            <LineKey tone={line.tone} />
            {isPickable ? (
              <select
                aria-label={`선 ${slot + 1} 에 그릴 스탯`}
                value={line.id}
                onChange={(event) => onPickSlot(slot, event.target.value)}
                className="h-5 max-w-32 min-w-0 truncate rounded-sm bg-transparent text-label text-ink-secondary hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
              >
                {candidates.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="truncate">{line.name}</span>
            )}
          </li>
        ))}
      </ul>
      {isPickable && (
        <span className="hidden shrink-0 text-ink-muted md:inline">
          스탯 {formatCount(candidates.length)}개 중 {formatCount(lines.length)}개
        </span>
      )}
      {strips.length > 0 && (
        <button
          type="button"
          aria-expanded={isStripsOpen}
          onClick={onToggleStrips}
          className="ml-auto flex h-5 shrink-0 items-center gap-1 rounded-sm px-1 text-label text-ink-secondary hover:bg-surface-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-accent motion-safe:transition-colors"
        >
          <span aria-hidden="true" className="inline-block size-1.5 rounded-full border border-ink-muted" />
          {stripsLabel(strips)} {formatCount(strips.length)}
          <span aria-hidden="true" className="text-ink-muted">
            {isStripsOpen ? "▾" : "▸"}
          </span>
        </button>
      )}
    </div>
  );
}

function LineKey({ tone }: { tone: LineTone }) {
  return <span aria-hidden="true" className={cn("inline-block h-0.5 w-3 shrink-0 rounded-full", LINE_KEY_CLASSES[tone])} />;
}

/** 표지 줄 — 같은 자리 표지는 한 묶음. 모양과 낱말(마우스를 올리면·읽기 프로그램)로 가르고 색만으로 뜻을 싣지 않는다. */
const MarkerRow = memo(function MarkerRow({ groups }: { groups: ReadonlyArray<MarkerGroup> }) {
  return (
    <ol aria-label="표지" className="relative h-4">
      {groups.map((group) => (
        <li
          key={group.key}
          title={group.title}
          aria-label={group.title}
          style={{ left: `${group.position * 100}%` }}
          className={cn(
            "absolute top-0.5 -translate-x-1/2 text-label leading-none whitespace-nowrap select-none",
            MARKER_TONE_CLASSES[group.tone],
          )}
        >
          {group.glyphs}
        </li>
      ))}
    </ol>
  );
});

function SelectedBand({ index, count }: { index: number; count: number }) {
  return (
    <span
      aria-hidden="true"
      // 고른 턴의 칸 — 칸 폭과 자리는 턴 수에 따라 달라지는 실행 중 값이다.
      style={{ left: `${(index / count) * 100}%`, width: `${100 / count}%` }}
      className="pointer-events-none absolute inset-y-0 bg-surface-raised"
    >
      <span className="absolute inset-y-0 left-1/2 w-px bg-ink" />
    </span>
  );
}

/** 세로 눈금선 — 패널 면에서 한 단 떨어진 1px 실선. 차트와 같은 안쪽 여백(`inset-y-1`) 안에서 자리를 잡는다. */
function GridLines({ chart }: { chart: ChartModel }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 inset-y-1">
      {chart.ticks.map((tick) => (
        <span key={tick} style={{ top: `${(1 - ratio(tick, chart.domain)) * 100}%` }} className="absolute inset-x-0 h-px bg-border" />
      ))}
    </div>
  );
}

/** 왼쪽 세로 눈금 숫자. 좁은 화면은 위아래 끝 눈금만 둔다 — 차트가 낮아 사이 눈금 글자가 겹친다. */
function YTicks({ chart }: { chart: ChartModel }) {
  return (
    <div aria-hidden="true">
      <div className="h-4" />
      <div className="relative h-14 md:h-22">
        <div className="absolute inset-x-0 inset-y-1">
          {chart.ticks.map((tick, order) => (
            <span
              key={tick}
              style={{ top: `${(1 - ratio(tick, chart.domain)) * 100}%` }}
              className={cn(
                "absolute right-1 -translate-y-1/2 text-label text-ink-muted tabular-nums",
                order !== 0 && order !== chart.ticks.length - 1 && "hidden md:block",
              )}
            >
              {formatCount(tick)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** 고른 턴·마우스가 가리키는 턴의 점 — 선마다 8px, 패널 면 색 2px 고리. */
function TurnDots({ chart, index, count }: { chart: ChartModel; index: number; count: number }) {
  const left = `${((index + 0.5) / count) * 100}%`;
  return chart.lines.map((line) => {
    const value = line.values[index];
    if (value == null) return null;
    return (
      <span
        key={line.id}
        style={{ left, top: `${(1 - ratio(value, chart.domain)) * 100}%` }}
        className={cn("absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface", LINE_KEY_CLASSES[line.tone])}
      />
    );
  });
}

function TickRow({ turnNumbers, selectedIndex }: { turnNumbers: ReadonlyArray<number>; selectedIndex: number }) {
  const count = turnNumbers.length;
  const ticks = tickIndexes(count);
  return (
    <ol aria-hidden="true" className="relative h-4 border-t border-border">
      {ticks.map((index) => (
        <li
          key={index}
          style={{ left: `${((index + 0.5) / count) * 100}%` }}
          className={cn(
            "absolute -translate-x-1/2 text-label tabular-nums",
            index === selectedIndex ? "font-semibold text-ink" : "text-ink-muted",
          )}
        >
          {turnNumbers[index]}
        </li>
      ))}
      {selectedIndex !== -1 && !ticks.includes(selectedIndex) && (
        <li
          style={{ left: `${((selectedIndex + 0.5) / count) * 100}%` }}
          className="absolute -translate-x-1/2 bg-surface-raised px-0.5 text-label font-semibold text-ink tabular-nums"
        >
          {turnNumbers[selectedIndex]}
        </li>
      )}
    </ol>
  );
}

type StripTracksProps = { strips: ReadonlyArray<StatStrip>; count: number; selectedIndex: number };

/**
 * 펼친 숨김 스탯 줄 — 줄마다 따로 세로 자리를 잡는 작은 다중. 바뀐 턴에만 흐린 점, 값이 유지되는 구간은 1px 선. 네 번째 선 색을
 * 얻지 않는다. 이름은 오른쪽 칸(`EndLabels`)에 같은 높이로 선다.
 */
const StripTracks = memo(function StripTracks({ strips, count, selectedIndex }: StripTracksProps) {
  return (
    <ol aria-label="숨김 스탯 줄" className="border-t border-border">
      {strips.map((strip) => (
        <li key={strip.id} aria-label={`${strip.name} · ${STRIP_TAG_LABELS[strip.tag]}`} className="relative h-6">
          {/* 좁은 화면은 오른쪽 이름 칸이 없어 줄 안에 이름과 숨김 낱말을 둔다. */}
          <span aria-hidden="true" className="absolute top-0 left-0 text-label leading-none md:hidden">
            <span className="text-ink-secondary">{strip.name}</span>{" "}
            <span className="text-ink-muted">{STRIP_TAG_LABELS[strip.tag]}</span>
          </span>
          {selectedIndex !== -1 && (
            <span
              aria-hidden="true"
              style={{ left: `${((selectedIndex + 0.5) / count) * 100}%` }}
              className="absolute inset-y-0 w-px bg-ink"
            />
          )}
          <div aria-hidden="true" className="absolute inset-x-0 inset-y-1.5">
            {strip.holds.map((hold) => (
              <span
                key={hold.from}
                style={{
                  left: `${((hold.from + 0.5) / count) * 100}%`,
                  width: `${((hold.to - hold.from) / count) * 100}%`,
                  top: `${(1 - hold.t) * 100}%`,
                }}
                className="absolute h-px bg-ink-muted"
              />
            ))}
            {strip.dots.map((dot) => (
              <span
                key={dot.index}
                style={{ left: `${((dot.index + 0.5) / count) * 100}%`, top: `${(1 - dot.t) * 100}%` }}
                className="absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink-muted"
              />
            ))}
          </div>
        </li>
      ))}
    </ol>
  );
});

type EndLabelsProps = {
  chart: ChartModel;
  labels: ReturnType<typeof placeEndLabels>;
  strips: ReadonlyArray<StatStrip>;
};

/** 오른쪽 칸 — 선 끝 이름표(겹치는 것은 숨긴다)와, 펼친 숨김 스탯 줄의 이름. 좁은 화면에서는 범례만 남긴다. */
function EndLabels({ chart, labels, strips }: EndLabelsProps) {
  return (
    <div aria-hidden="true" className="hidden md:block">
      <div className="h-4" />
      <div className="relative h-14 md:h-22">
        <div className="absolute inset-x-0 inset-y-1">
          {chart.lines.length > 0 &&
            labels
              .filter((label) => label.isShown)
              .map((label) => (
                <span
                  key={label.id}
                  style={{ top: `${(1 - label.t) * 100}%` }}
                  className="absolute inset-x-0 flex -translate-y-1/2 items-center gap-1 pl-1.5 text-label text-ink-secondary"
                >
                  <LineKey tone={label.tone} />
                  <span className="truncate">{label.name}</span>
                </span>
              ))}
        </div>
      </div>
      <div className="h-4" />
      {strips.length > 0 && (
        <ol className="border-t border-transparent">
          {strips.map((strip) => (
            <li
              key={strip.id}
              title={`${strip.name} · ${STRIP_TAG_LABELS[strip.tag]}`}
              // 이름 아래에 숨김 낱말 — 두 줄을 글자 높이 그대로(leading-none) 24px 줄 안에 넣는다.
              className="flex h-6 min-w-0 flex-col justify-center gap-0.5 pl-1.5 text-label leading-none"
            >
              <span className="flex min-w-0 items-center gap-1 text-ink-secondary">
                <span aria-hidden="true" className="inline-block size-1.5 shrink-0 rounded-full border border-ink-muted" />
                <span className="truncate">{strip.name}</span>
              </span>
              <span className="truncate text-ink-muted">{STRIP_TAG_LABELS[strip.tag]}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

type ReadoutProps = {
  index: number;
  count: number;
  summary: TurnSummary | undefined;
  chart: ChartModel;
  strips: ReadonlyArray<StatStrip>;
  groups: ReadonlyArray<MarkerGroup>;
};

/**
 * 한 턴의 툴팁 — 그 턴의 모든 선 값(값이 앞, 이름이 뒤)과 변화량, 펼친 숨김 스탯의 유지 값, 그 턴 자리의 표지. 값이 없으면 "기록
 * 없음"이고, 그 턴이 시작한 값을 모르면 변화량 자리에 "Δ 모름"이다. 띠 오른쪽 절반에서는 십자선 왼쪽으로 뜬다.
 */
function Readout({ index, count, summary, chart, strips, groups }: ReadoutProps) {
  const ratioX = (index + 0.5) / count;
  const marks = groups.filter((group) => group.index === index);
  return (
    <div
      role="tooltip"
      style={{ left: `${ratioX * 100}%` }}
      className={cn(
        "pointer-events-none absolute top-4 z-20 w-max max-w-64 rounded-md bg-surface px-2 py-1.5 text-data shadow-overlay",
        ratioX > 0.55 ? "-translate-x-full -ml-3" : "ml-3",
      )}
    >
      <p className="font-semibold text-ink tabular-nums">턴 {summary?.turn ?? "?"}</p>
      <ul className="mt-1 space-y-0.5">
        {chart.lines.map((line) => {
          const value = line.values[index];
          return (
            <li key={line.id} className="flex items-center gap-1.5 tabular-nums">
              <LineKey tone={line.tone} />
              {value == null ? (
                <span className="text-ink-muted">기록 없음</span>
              ) : (
                <span className="font-semibold text-ink">{formatCount(value)}</span>
              )}
              <span className="text-ink-secondary">{line.name}</span>
              <span className="text-ink-muted">{deltaText(summary, line.name, value)}</span>
            </li>
          );
        })}
        {strips.map((strip) => {
          const held = heldValueAt(strip, index);
          return (
            <li key={strip.id} className="flex items-center gap-1.5 tabular-nums">
              <span aria-hidden="true" className="inline-block size-1.5 shrink-0 rounded-full border border-ink-muted" />
              {held === undefined ? (
                <span className="text-ink-muted">기록 없음</span>
              ) : (
                <span className="font-semibold text-ink">{formatCount(held)}</span>
              )}
              <span className="text-ink-secondary">{strip.name}</span>
              <span className="text-ink-muted">{STRIP_TAG_LABELS[strip.tag]}</span>
            </li>
          );
        })}
      </ul>
      {marks.length > 0 && (
        <ul className="mt-1 space-y-0.5 border-t border-border pt-1">
          {marks.map((group) => (
            <li key={group.key} className="flex gap-1.5">
              <span aria-hidden="true" className={MARKER_TONE_CLASSES[group.tone]}>
                {group.glyphs}
              </span>
              <span className="text-ink-secondary">{group.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * 툴팁의 변화량 칸. 그 턴에 바뀐 스탯은 측정 서버가 낸 변화량(시작 값을 모르면 "Δ 모름"), 바뀌지 않은 스탯은 시작 값을 알면 비우고
 * (바뀌지 않았다) 모르면 "Δ 모름"이다. 값이 없는 칸은 변화량도 적지 않는다.
 */
function deltaText(summary: TurnSummary | undefined, name: string, value: number | null | undefined): string {
  if (summary === undefined || value == null) return "";
  const change = summary.driverStatChanges.find((candidate) => candidate.name === name);
  if (change !== undefined) return formatDeltaValue(change.delta ?? undefined);
  return summary.statsStartKnown ? "" : formatDeltaValue(undefined);
}

/** 읽기 프로그램에 줄 고른 턴의 값 — 선마다 "이름 값(변화량)". */
function describeTurn(chart: ChartModel, summary: TurnSummary | undefined, index: number): string {
  const parts = chart.lines.map((line) => {
    const value = line.values[index];
    if (value == null) return `${line.name} 기록 없음`;
    const delta = deltaText(summary, line.name, value);
    return delta === "" ? `${line.name} ${formatCount(value)}` : `${line.name} ${formatCount(value)}(${delta})`;
  });
  return parts.length === 0 ? "스탯 선 없음" : parts.join(", ");
}

function ratio(value: number, [low, high]: readonly [number, number]): number {
  return high === low ? 0.5 : (value - low) / (high - low);
}
