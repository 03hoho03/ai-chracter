import { memo, useEffect, type RefObject } from "react";

import { assertNever } from "@/shared/lib/assertNever";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/formatNumber";
import { scrollIntoNearest } from "@/shared/lib/scrollIntoNearest";

import { formatStatDelta, type TurnRow, type Utterance } from "../model/turnRows";
import { StatDot } from "./StatDot";

type TurnListProps = {
  rows: ReadonlyArray<TurnRow>;
  selectedTurn: number | undefined;
  /** 지표 표본 수(응답이 있는 턴). 지표를 아직 못 받았으면 undefined. */
  scored: number | undefined;
  listRef: RefObject<HTMLOListElement | null>;
  onSelectTurn: (turn: number) => void;
};

/**
 * 왼쪽 턴 목록. 한 행 = 턴 번호 · 사용자 발화 한 줄 · 스탯 Δ 점 · 플래그 약자 · 표지(보충·교체·유실) · 시도 수. 행을 누르거나
 * 포커스가 오면 그 턴을 고른다 — `j`/`k` 는 포커스를 다음 행으로 옮겨 고르므로, 이어 누른 Enter·Tab 이 고른 행에서 시작한다.
 */
export function TurnList({ rows, selectedTurn, scored, listRef, onSelectTurn }: TurnListProps) {
  // 고른 턴이 목록 밖에서 바뀌어도(타임라인·불일치 목록·주소로 연 턴) 목록 스크롤이 그 행을 따라간다. 즉시, 가장 가까운 자리로.
  // 스크롤만 옮기고 순차 초점 시작점은 그대로 둔다(`scrollIntoNearest`) — 화면을 연 직후 첫 Tab 이 헤더에서 시작해야 한다.
  useEffect(() => {
    if (selectedTurn === undefined) return;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-turn="${selectedTurn}"]`);
    if (row) scrollIntoNearest(row);
  }, [listRef, selectedTurn]);

  return (
    <>
      <div className="sticky top-0 z-10 flex h-8 items-center gap-2 border-b border-border bg-surface px-3">
        <h2 className="text-section text-ink">턴</h2>
        <span className="text-data text-ink-muted tabular-nums">
          {formatCount(rows.length)}
          {scored !== undefined && ` · 표본 ${formatCount(scored)}`}
        </span>
      </div>
      <ol ref={listRef} aria-label="턴">
        {rows.map((row) => (
          <TurnListRow key={row.turn} row={row} isActive={row.turn === selectedTurn} onSelect={onSelectTurn} />
        ))}
      </ol>
    </>
  );
}

type TurnListRowProps = {
  row: TurnRow;
  isActive: boolean;
  onSelect: (turn: number) => void;
};

// 행은 메모한다 — j/k 로 옮길 때 바뀌는 것은 앞뒤 두 행의 `isActive` 뿐이다.
const TurnListRow = memo(function TurnListRow({ row, isActive, onSelect }: TurnListRowProps) {
  return (
    <li>
      <button
        type="button"
        data-turn={row.turn}
        aria-current={isActive ? "true" : undefined}
        tabIndex={isActive ? 0 : -1}
        onClick={() => onSelect(row.turn)}
        onFocus={isActive ? undefined : () => onSelect(row.turn)}
        className={cn(
          "grid h-7 w-full scroll-mt-8 grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-1.5 border-b border-border pr-2 text-left text-data",
          "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent motion-safe:transition-colors",
          isActive ? "bg-surface-raised outline-1 -outline-offset-1 outline-accent" : "hover:bg-surface-raised",
        )}
      >
        <span className={cn("text-right tabular-nums", isActive ? "font-semibold text-ink" : "text-ink-muted")}>
          {row.turn}
        </span>
        <UtteranceText utterance={row.utterance} />
        <span className="flex items-center gap-1">
          {row.deltas.length > 0 && (
            <span className="flex items-center gap-0.5" aria-label={describeDeltas(row)}>
              {row.deltas.map((delta) => (
                <StatDot key={delta.name} tone={delta.tone} />
              ))}
            </span>
          )}
          {row.flags.map((flag) => (
            <span
              key={flag.key}
              title={flag.label}
              aria-label={flag.label}
              className={cn(
                "inline-flex h-4 min-w-4 items-center justify-center rounded-sm bg-surface-sunken px-0.5 text-label",
                flag.isDanger ? "text-danger" : "text-ink-secondary",
              )}
            >
              {flag.abbr}
            </span>
          ))}
          {row.isLost && <span className="text-label text-danger">응답 없음</span>}
          {row.isSupplemented && (
            <span title="clientTurn 없는 사람 보충 줄 — 턴 번호는 방 턴 수로 대신했다" className="text-label text-ink-muted">
              보충
            </span>
          )}
          {row.isReplaced && (
            <span title="재생성·수정으로 응답이 교체됐다" className="text-label text-warn">
              교체
            </span>
          )}
          {row.attemptCount > 1 && (
            <span title={`시도 ${row.attemptCount}번`} className="text-label text-ink-secondary tabular-nums">
              ×{row.attemptCount}
            </span>
          )}
        </span>
      </button>
    </li>
  );
});

function UtteranceText({ utterance }: { utterance: Utterance }) {
  switch (utterance.kind) {
    case "user":
      return <span className="truncate text-ink">{utterance.text}</span>;
    case "shortcut":
      return (
        <span className="truncate text-ink-secondary">
          단축어 · <span className="text-ink">{utterance.name}</span>
        </span>
      );
    case "none":
      return <span className="truncate text-ink-muted">발화 없음</span>;
    default:
      return assertNever(utterance);
  }
}

function describeDeltas(row: TurnRow): string {
  return row.deltas.map((delta) => `${delta.name} ${formatStatDelta(delta)}`).join(", ");
}
