import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check, ChevronDown, Lock } from "lucide-react";
import type { MouseEvent } from "react";

import {
  toTimelineSegments,
  toTurnRangeLabel,
  type SourceTurn,
  type TimelineSegment,
  type TurnState,
} from "../model/sourceTimeline";

/** 뺀 대화 묶음이 이만큼 길면 접어 둔다 — 수백 턴 방에서 고르지 않은 대화가 화면을 다 차지하지 않게. 짧은 묶음은 늘 펼친다. */
const GAP_FOLD_MIN = 4;

const STATE_LABEL: Record<TurnState, string> = {
  include: "담기",
  context: "맥락만",
  exclude: "빼기",
  locked: "이미 씀",
};

type SourceTimelineProps = {
  turns: readonly SourceTurn[];
  states: ReadonlyMap<string, TurnState>;
  /** 저장 뒤 원문이 바뀐 턴. */
  changedKeys: ReadonlySet<string>;
  /** 펼친 긴 뺀 대화 묶음(첫 턴의 열쇠). */
  expandedGapKeys: ReadonlySet<string>;
  onToggleTurn: (turn: SourceTurn, options: { isRange: boolean }) => void;
  /** 묶음 전체를 맥락으로 보내거나 맥락에서 뺀다. */
  onSetGap: (turns: readonly SourceTurn[], target: "context" | "exclude") => void;
  onToggleGapExpanded: (key: string) => void;
};

/**
 * 담을 대화 타임라인 — 턴마다 한 줄(번호·두 줄 발췌)이고, 맞닿은 같은 상태의 턴이 한 묶음이다.
 *
 * - 턴 줄은 담기 토글 버튼이다(`aria-pressed`). 누르면 담기 ↔ 빼기, 맥락이면 담기가 된다. Shift 를 누른 채 누르면 앞에 누른
 *   턴부터 그 턴까지 같은 상태로 바꾼다.
 * - 뺀 대화 묶음과 맥락 묶음은 머리에 "맥락으로 보내기"·"맥락에서 빼기"를 단다 — 맥락은 소설에 옮기지 않지만 AI 에게는 함께
 *   보내는 대화라, 묶음마다 이용자가 직접 보낸다(기본은 보내지 않는다).
 * - 이미 화로 쓴 대화는 버튼 없는 한 줄로 접는다(다시 담을 수 없다).
 *
 * 담기 표시는 체크 상자와 같은 모양이다 — 강조색은 담은 턴의 표시에만 있고, 줄 자체는 무채색이다.
 */
export function SourceTimeline({
  turns,
  states,
  changedKeys,
  expandedGapKeys,
  onToggleTurn,
  onSetGap,
  onToggleGapExpanded,
}: SourceTimelineProps) {
  const segments = toTimelineSegments(turns, states);
  return (
    <ol aria-label="대화 턴" className="flex flex-col gap-1">
      {segments.map((segment) => (
        <SegmentItems
          key={segment.turns[0]?.key}
          segment={segment}
          changedKeys={changedKeys}
          isExpanded={expandedGapKeys.has(segment.turns[0]?.key ?? "")}
          onToggleTurn={onToggleTurn}
          onSetGap={onSetGap}
          onToggleGapExpanded={onToggleGapExpanded}
        />
      ))}
    </ol>
  );
}

type SegmentItemsProps = Omit<SourceTimelineProps, "turns" | "states" | "expandedGapKeys"> & {
  segment: TimelineSegment;
  isExpanded: boolean;
};

function SegmentItems({ segment, changedKeys, isExpanded, onToggleTurn, onSetGap, onToggleGapExpanded }: SegmentItemsProps) {
  const rangeLabel = toTurnRangeLabel(segment.turns);
  const firstKey = segment.turns[0]?.key ?? "";

  if (segment.state === "locked") {
    return (
      <li className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm break-keep text-muted-foreground">
        <Lock aria-hidden className="size-4 shrink-0" />
        <span className="min-w-0 flex-1">이미 쓴 대화 {rangeLabel}</span>
        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-badge font-medium">잠김</span>
      </li>
    );
  }

  const rows = segment.turns.map((turn) => (
    <li key={turn.key}>
      <TurnRow turn={turn} state={segment.state} isChanged={changedKeys.has(turn.key)} onToggle={onToggleTurn} />
    </li>
  ));
  if (segment.state === "include") return rows;

  const isFoldable = segment.state === "exclude" && segment.turns.length >= GAP_FOLD_MIN;
  const isOpen = !isFoldable || isExpanded;
  const groupId = `source-gap-${firstKey}`;
  return (
    <li className="flex flex-col gap-1">
      <div
        data-segment-from={segment.turns[0]?.number}
        data-segment-to={segment.turns.at(-1)?.number}
        className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-dashed border-border px-3 py-2"
      >
        <p className="min-w-0 flex-1 text-sm break-keep text-muted-foreground">
          {segment.state === "exclude" ? (
            <>
              뺀 대화 {rangeLabel} · <span className="whitespace-nowrap">AI에 보내지 않아요</span>
            </>
          ) : (
            <>
              맥락으로만 보내는 대화 {rangeLabel} · <span className="whitespace-nowrap">소설에는 옮기지 않아요</span>
            </>
          )}
        </p>
        <div className="flex shrink-0 items-center gap-1">
          {isFoldable && (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              aria-expanded={isOpen}
              aria-controls={groupId}
              onClick={() => onToggleGapExpanded(firstKey)}
            >
              {isOpen ? "접기" : "펼치기"}
              <ChevronDown aria-hidden className={cn("motion-safe:transition-transform", isOpen && "rotate-180")} />
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-label={segment.state === "exclude" ? `${rangeLabel}을 맥락으로 보내기` : `${rangeLabel}을 맥락에서 빼기`}
            onClick={() => onSetGap(segment.turns, segment.state === "exclude" ? "context" : "exclude")}
          >
            {segment.state === "exclude" ? "맥락으로 보내기" : "맥락에서 빼기"}
          </Button>
        </div>
      </div>
      {isOpen && (
        <ol id={groupId} aria-label={`${rangeLabel} 턴`} className="flex flex-col gap-1">
          {rows}
        </ol>
      )}
    </li>
  );
}

type TurnRowProps = {
  turn: SourceTurn;
  state: TurnState;
  isChanged: boolean;
  onToggle: (turn: SourceTurn, options: { isRange: boolean }) => void;
};

// 포커스는 하우스 레시피(불투명 `border-ring` 이 3:1 을 지고 바깥 반투명 링을 더한다).
const ROW_CLASS =
  "flex w-full items-start gap-3 rounded-lg border border-transparent px-3 py-2 text-left outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 motion-safe:transition-colors";

function TurnRow({ turn, state, isChanged, onToggle }: TurnRowProps) {
  const isIncluded = state === "include";
  return (
    <button
      type="button"
      data-turn={turn.number}
      aria-pressed={isIncluded}
      className={ROW_CLASS}
      onClick={(event: MouseEvent<HTMLButtonElement>) => onToggle(turn, { isRange: event.shiftKey })}
    >
      <StateMark state={state} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-xs text-muted-foreground tabular-nums">
          {turn.number}턴
          {isChanged && <span className="font-medium text-foreground"> · 고른 뒤 바뀜</span>}
        </span>
        <span className={cn("line-clamp-2 text-sm break-keep", state === "include" ? "text-foreground" : "text-muted-foreground")}>
          {turn.excerpt === "" ? "(빈 메시지)" : turn.excerpt}
        </span>
      </span>
      <span className="sr-only">, {STATE_LABEL[state]}</span>
    </button>
  );
}

/** 줄 앞 상태 표시. 담기는 체크 상자의 켜짐과 같은 채움, 맥락은 점선 상자, 빼기는 빈 상자다. */
function StateMark({ state }: { state: TurnState }) {
  return (
    <span
      aria-hidden
      className={cn(
        "mt-1 flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
        state === "include" && "border-primary bg-primary text-primary-foreground",
        state === "context" && "border-dashed border-foreground",
        (state === "exclude" || state === "locked") && "border-input",
      )}
    >
      {state === "include" && <Check className="size-3.5" />}
    </span>
  );
}
