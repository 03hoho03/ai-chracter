import type { KeyboardEvent, MouseEvent, RefObject } from "react";

import type { TimelineMarker } from "@/shared/api/client";
import { cn } from "@/shared/lib/cn";

import { MARKER_STYLES } from "../model/detailLabels";

type StateTimelineProps = {
  /** 런의 턴 번호(서버 순서). 번호가 건너뛰어도 칸은 턴마다 같은 폭이다. */
  turns: ReadonlyArray<number>;
  markers: ReadonlyArray<TimelineMarker>;
  selectedTurn: number | undefined;
  timelineRef: RefObject<HTMLDivElement | null>;
  onSelectTurn: (turn: number) => void;
};

const TONE_CLASSES = {
  muted: "text-ink-muted",
  warn: "text-warn",
  danger: "text-danger",
} as const;

/** 축 눈금을 몇 턴마다 둘지 — 칸이 좁아도 숫자끼리 겹치지 않을 만큼. */
const TICK_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500] as const;
const MAX_TICKS = 12;

/**
 * 상태 타임라인 자리. 지금은 턴 번호 축과 표지 줄(엔딩·기억 노트·요약·rebase·재생성·수정·실패 등)만 그리고, 스탯 선 그래프는 이
 * 띠의 높이를 그대로 쓰는 다음 판이 채운다 — 그래서 띠 높이를 고정하고 바깥과는 턴 번호·표지·고른 턴·고르기 콜백으로만 닿는다.
 *
 * 띠를 누르면 가장 가까운 턴을 고르고, 포커스(`g`)가 있을 때 ←/→ 로 턴을 옮긴다. 드라이버 줄에서 온 표지(rebase 등)는 그 턴 뒤라
 * 턴 사이 칸에 놓는다.
 */
export function StateTimeline({ turns, markers, selectedTurn, timelineRef, onSelectTurn }: StateTimelineProps) {
  const count = turns.length;
  const selectedIndex = selectedTurn === undefined ? -1 : turns.indexOf(selectedTurn);
  const ticks = tickIndexes(count);

  function turnAt(clientX: number, element: HTMLElement): number | undefined {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || count === 0) return undefined;
    const index = Math.min(count - 1, Math.max(0, Math.floor(((clientX - rect.left) / rect.width) * count)));
    return turns[index];
  }

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    const turn = turnAt(event.clientX, event.currentTarget);
    if (turn !== undefined) onSelectTurn(turn);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = turns[Math.min(count - 1, Math.max(0, (selectedIndex === -1 ? 0 : selectedIndex) + step))];
    if (next !== undefined) onSelectTurn(next);
  }

  return (
    <section aria-label="상태 타임라인" className="h-16 shrink-0 border-b border-border bg-surface px-3 py-1.5">
      <div
        ref={timelineRef}
        tabIndex={0}
        role="group"
        aria-label={`턴 ${selectedTurn ?? "-"} / ${count} — 누르면 그 턴, ←/→ 로 옮긴다`}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        className="relative h-full cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      >
        {selectedIndex !== -1 && (
          <span
            aria-hidden="true"
            // 고른 턴의 칸 — 칸 폭과 자리는 턴 수에 따라 달라지는 실행 중 값이다.
            style={{ left: `${(selectedIndex / count) * 100}%`, width: `${100 / count}%` }}
            className="absolute inset-y-0 bg-surface-raised"
          >
            <span className="absolute inset-y-0 left-1/2 w-px bg-ink" />
          </span>
        )}
        <ol aria-label="표지" className="absolute inset-x-0 top-0 h-6">
          {markers.map((marker, index) => {
            const style = MARKER_STYLES[marker.kind];
            const position = markerPosition(turns, marker, style.isAfterTurn);
            const where = style.isAfterTurn ? `턴 ${marker.turn} 뒤` : `턴 ${marker.turn}`;
            const title = [where, style.label, marker.detail].filter(Boolean).join(" · ");
            return (
              <li
                // 서버 순서 그대로이고 바뀌지 않는다 — 같은 턴·같은 종류 표지가 여럿일 수 있어 순번을 함께 쓴다.
                key={`${marker.kind}-${marker.turn}-${index}`}
                title={title}
                aria-label={title}
                style={{ left: `${position * 100}%` }}
                className={cn(
                  "absolute top-1 -translate-x-1/2 text-label leading-none select-none",
                  TONE_CLASSES[style.tone],
                )}
              >
                {style.glyph}
              </li>
            );
          })}
        </ol>
        <div aria-hidden="true" className="absolute inset-x-0 top-7 border-t border-border" />
        <ol aria-hidden="true" className="absolute inset-x-0 top-8 h-4">
          {ticks.map((index) => (
            <li
              key={index}
              style={{ left: `${((index + 0.5) / count) * 100}%` }}
              className={cn(
                "absolute -translate-x-1/2 text-label tabular-nums",
                index === selectedIndex ? "font-semibold text-ink" : "text-ink-muted",
              )}
            >
              {turns[index]}
            </li>
          ))}
          {selectedIndex !== -1 && !ticks.includes(selectedIndex) && (
            <li
              style={{ left: `${((selectedIndex + 0.5) / count) * 100}%` }}
              className="absolute -translate-x-1/2 bg-surface-raised px-0.5 text-label font-semibold text-ink tabular-nums"
            >
              {turns[selectedIndex]}
            </li>
          )}
        </ol>
      </div>
    </section>
  );
}

/** 표지의 가로 자리(0~1). 턴 표지는 그 턴 칸 가운데, 턴 뒤 표지는 그 턴과 다음 턴 사이. 런에 없는 턴이면 가까운 쪽 끝. */
function markerPosition(turns: ReadonlyArray<number>, marker: TimelineMarker, isAfterTurn: boolean): number {
  const count = turns.length;
  if (count === 0) return 0;
  const index = turns.indexOf(marker.turn);
  if (index === -1) {
    const first = turns[0] ?? 0;
    return marker.turn < first ? 0 : 1;
  }
  return isAfterTurn ? (index + 1) / count : (index + 0.5) / count;
}

/** 눈금을 둘 턴 칸 — 처음·끝과, 칸 수에 맞춘 간격마다. */
function tickIndexes(count: number): number[] {
  if (count === 0) return [];
  const step = TICK_STEPS.find((candidate) => count / candidate <= MAX_TICKS) ?? Math.ceil(count / MAX_TICKS);
  const indexes = new Set<number>([0, count - 1]);
  for (let index = step - 1; index < count - 1; index += step) {
    // 끝 눈금과 너무 붙으면 뺀다.
    if (count - 1 - index >= step / 2) indexes.add(index);
  }
  return [...indexes].sort((a, b) => a - b);
}
