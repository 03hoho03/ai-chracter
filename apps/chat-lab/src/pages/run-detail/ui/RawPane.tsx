import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";

import { assertNever } from "@/shared/lib/assertNever";
import { cn } from "@/shared/lib/cn";
import { formatCount } from "@/shared/lib/formatNumber";

import { diffLines, foldDiff } from "../model/lineDiff";
import { splitByMatches, type TextMatch } from "../model/rawSearch";
import type { RawView } from "../model/rawSource";
import type { DumpSource, RawTab } from "../model/runDetailSearch";

type SourceOption = {
  value: string;
  label: string;
};

type RawPaneProps = {
  /** 지금 그린 턴. 턴이 바뀌면 비교 탭의 견줄 앞선 덤프 고르기를 처음(첫째)으로 되돌린다 — 턴마다 앞선 덤프 수가 다르다. */
  turn: number;
  tab: RawTab;
  onTabChange: (tab: RawTab) => void;
  sourceOptions: ReadonlyArray<SourceOption>;
  sourceValue: string;
  source: DumpSource;
  onSourceChange: (value: string) => void;
  view: RawView;
  promptLength: number | undefined;
  instructionLength: number | undefined;
  /** 앞선 생성 덤프의 프롬프트(비교 탭). 생성 덤프를 보고 있고 앞선 덤프가 있을 때만. */
  earlierPrompts: ReadonlyArray<string | undefined>;
  query: string;
  onQueryChange: (query: string) => void;
  matches: ReadonlyArray<TextMatch>;
  currentMatch: number;
  onStepMatch: (step: 1 | -1) => void;
  onCloseSearch: () => void;
  searchRef: RefObject<HTMLInputElement | null>;
  isFolded: boolean;
  onToggleFold: () => void;
};

const COMPARE_CONTEXT_LINES = 2;

const DIFF_MARKS = { removed: "−", added: "+", same: " " } as const;

/**
 * 가운데 아래 원문 칸 — 프롬프트 원문 · 지시문 원문 · 앞선 생성 덤프와 비교. 출처(생성·앞선 생성·판정·백그라운드 덤프 줄)를
 * 고르고, 원문 안을 검색한다(`/` 로 칸에, Enter·`n` 다음, Shift+Enter·`N` 이전, Esc 닫기). 원문이 없으면 왜 없는지를 문장으로.
 * 원문은 줄바꿈을 지키고 가로 스크롤 없이 접어 넣는다.
 */
export function RawPane(props: RawPaneProps) {
  const { tab, onTabChange, isFolded, onToggleFold, source, earlierPrompts } = props;
  const canCompare = source.kind === "generation" && earlierPrompts.length > 0;
  const activeTab = tab === "compare" && !canCompare ? "prompt" : tab;

  return (
    <div className={cn("flex min-h-0 flex-col border-t border-border", isFolded ? "shrink-0" : "flex-1")}>
      <div className="flex shrink-0 flex-wrap items-center gap-x-2 border-b border-border bg-surface px-2">
        <div role="tablist" aria-label="원문" className="flex min-w-0 items-center">
          <RawTabButton isSelected={activeTab === "prompt"} onClick={() => onTabChange("prompt")}>
            프롬프트 원문
            {props.promptLength !== undefined && <Count value={props.promptLength} />}
          </RawTabButton>
          <RawTabButton isSelected={activeTab === "instruction"} onClick={() => onTabChange("instruction")}>
            지시문 원문
            {props.instructionLength !== undefined && <Count value={props.instructionLength} />}
          </RawTabButton>
          {canCompare && (
            <RawTabButton isSelected={activeTab === "compare"} onClick={() => onTabChange("compare")}>
              앞선 생성 덤프와 비교
            </RawTabButton>
          )}
        </div>
        <div className="ml-auto flex items-center gap-1 py-1">
          <label className="flex items-center gap-1 text-label text-ink-muted">
            <span className="sr-only sm:not-sr-only">출처</span>
            <select
              value={props.sourceValue}
              onChange={(event) => props.onSourceChange(event.target.value)}
              className="h-6 max-w-48 rounded-sm border border-border bg-surface px-1 font-mono text-label text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              {props.sourceOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            aria-expanded={!isFolded}
            onClick={onToggleFold}
            className="h-6 rounded-sm px-1.5 text-label text-ink-secondary hover:bg-surface-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            {isFolded ? "원문 펼치기" : "원문 접기"}
          </button>
        </div>
      </div>
      {!isFolded && (
        <div className="min-h-0 flex-1 overflow-auto px-3 pt-2 pb-4">
          {activeTab === "compare" ? (
            <CompareBody key={props.turn} view={props.view} earlierPrompts={earlierPrompts} />
          ) : (
            <SearchableRaw {...props} />
          )}
        </div>
      )}
    </div>
  );
}

function SearchableRaw({
  view,
  query,
  onQueryChange,
  matches,
  currentMatch,
  onStepMatch,
  onCloseSearch,
  searchRef,
}: RawPaneProps) {
  const rawRef = useRef<HTMLPreElement>(null);

  // 지금 일치를 원문 칸 안에 들인다 — 바깥 스크롤(문서)은 움직이지 않게 가장 가까운 자리로. 일치 목록은 원문 글이나 검색어가
  // 바뀔 때만 새로 만들어지므로, 화면이 다른 까닭(키 입력·다시 받기)으로 다시 그려질 때는 읽던 자리로 되감지 않는다.
  useEffect(() => {
    rawRef.current?.querySelector("[data-current-match]")?.scrollIntoView({ block: "nearest" });
  }, [currentMatch, matches]);

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      onStepMatch(event.shiftKey ? -1 : 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onCloseSearch();
    }
  }

  const position = matchPosition(query, matches.length, currentMatch);

  return (
    <>
      <div role="search" className="sticky top-0 z-10 -mx-3 mb-2 bg-surface px-3 pb-1">
        <div className="flex h-7 items-center gap-2 rounded-md border border-border bg-surface-sunken px-2 focus-within:border-accent">
          <span aria-hidden="true" className="text-ink-muted">
            ⌕
          </span>
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="원문 검색 ( / )"
            aria-label="원문 검색"
            className="min-w-0 flex-1 bg-transparent text-data text-ink outline-none placeholder:text-ink-muted"
          />
          <span aria-live="polite" className="shrink-0 text-label text-ink-muted tabular-nums">
            {position}
          </span>
          <button
            type="button"
            aria-label="이전 일치"
            disabled={matches.length === 0}
            onClick={() => onStepMatch(-1)}
            className="rounded-sm px-1 text-label text-ink-secondary enabled:hover:text-ink disabled:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent"
          >
            ↑
          </button>
          <button
            type="button"
            aria-label="다음 일치"
            disabled={matches.length === 0}
            onClick={() => onStepMatch(1)}
            className="rounded-sm px-1 text-label text-ink-secondary enabled:hover:text-ink disabled:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent"
          >
            ↓
          </button>
        </div>
      </div>
      {view.kind === "text" ? (
        <pre
          ref={rawRef}
          className="rounded-md bg-surface-sunken p-3 font-mono text-mono whitespace-pre-wrap text-ink wrap-anywhere"
        >
          <HighlightedText text={view.text} matches={matches} currentMatch={currentMatch} />
        </pre>
      ) : (
        <RawAbsent view={view} />
      )}
    </>
  );
}

/** 검색 칸 옆 "3/12" — 검색어가 없으면 비우고, 있는데 일치가 없으면 0/0. */
function matchPosition(query: string, count: number, current: number): string {
  if (count > 0) return `${current + 1}/${count}`;
  return query.trim() === "" ? "" : "0/0";
}

function HighlightedText({
  text,
  matches,
  currentMatch,
}: {
  text: string;
  matches: ReadonlyArray<TextMatch>;
  currentMatch: number;
}) {
  const segments = useMemo(() => splitByMatches(text, matches, currentMatch), [text, matches, currentMatch]);
  return segments.map((segment, index) => {
    // 조각은 원문 순서대로 한 번 만들어지고 순서가 바뀌지 않는다.
    if (segment.kind === "plain") return <span key={index}>{segment.text}</span>;
    return (
      <mark
        key={index}
        data-current-match={segment.kind === "current" ? "" : undefined}
        className={cn("rounded-sm", segment.kind === "current" ? "bg-accent text-accent-ink" : "bg-accent/16 text-ink")}
      >
        {segment.text}
      </mark>
    );
  });
}

/** 원문이 없을 때 — 왜 없는지. 덤프가 없는 묶음·원문을 뺀 기록·고르지 않은 시도·원래 없는 칸이 같은 모양이 되지 않게. */
function RawAbsent({ view }: { view: Exclude<RawView, { kind: "text" }> }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-surface-raised px-2 py-1.5 text-data text-ink-secondary">
      <span aria-hidden="true" className="font-semibold text-ink-muted">
        i
      </span>
      <p>{absentSentence(view)}</p>
    </div>
  );
}

function absentSentence(view: Exclude<RawView, { kind: "text" }>): string {
  switch (view.kind) {
    case "noDumpFile":
      return view.text;
    case "notSelectedAttempt":
      return view.earlierCount > 0
        ? `덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다. 이 턴의 앞선 생성 덤프 ${view.earlierCount}개는 어느 시도의 것인지 가르지 않아 출처에서 따로 연다.`
        : "덤프 없음 — 생성 덤프는 DB 응답으로 고른 시도에만 붙는다.";
    case "noDumpForAttempt":
      return "덤프 없음 — 이 출처에 붙은 덤프 줄이 없다.";
    case "excluded":
      return "원문 제외 — 이 기록은 프롬프트·지시문 원문을 빼고 만들었다.";
    case "emptyPrompt":
      return "이 덤프 줄의 프롬프트 칸이 비어 있다 — 칸은 있지만 글이 아닌 값이 적혀 있다.";
    case "noField":
      return "이 덤프 줄에는 지시문 칸이 없다 — 지시문을 따로 보내지 않은 호출이다.";
    default:
      return assertNever(view);
  }
}

function CompareBody({ view, earlierPrompts }: { view: RawView; earlierPrompts: ReadonlyArray<string | undefined> }) {
  const [earlierIndex, setEarlierIndex] = useState(0);
  const earlier = earlierPrompts[Math.min(earlierIndex, earlierPrompts.length - 1)];
  const current = view.kind === "text" ? view.text : undefined;
  const folded = useMemo(
    () =>
      earlier === undefined || current === undefined
        ? undefined
        : foldDiff(diffLines(earlier, current), COMPARE_CONTEXT_LINES),
    [earlier, current],
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-data text-ink-secondary">
        <span>
          <span className="font-mono">−</span> 앞선 생성 덤프에만 · <span className="font-mono">+</span> 지금 시도의 생성
          덤프에만
        </span>
        {earlierPrompts.length > 1 && (
          <select
            value={earlierIndex}
            onChange={(event) => setEarlierIndex(Number(event.target.value))}
            aria-label="견줄 앞선 생성 덤프"
            className="h-6 rounded-sm border border-border bg-surface px-1 text-label text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            {earlierPrompts.map((_, index) => (
              // 앞선 덤프 목록은 그 턴의 파일 순서라 바뀌지 않는다.
              <option key={index} value={index}>
                앞선 생성 덤프 {index + 1}
              </option>
            ))}
          </select>
        )}
      </div>
      {folded === undefined ? (
        <RawAbsent view={view.kind === "text" ? { kind: "excluded" } : view} />
      ) : (
        <pre className="rounded-md bg-surface-sunken py-2 font-mono text-mono whitespace-pre-wrap text-ink wrap-anywhere">
          {folded.map((line, index) => {
            // 비교 결과는 두 원문에서 한 번 만들어지고 순서가 바뀌지 않는다.
            if (line.kind === "folded") {
              return (
                <span key={index} className="block px-3 text-label text-ink-muted">
                  ⋯ 같은 줄 {formatCount(line.count)}개
                </span>
              );
            }
            return (
              <span
                key={index}
                className={cn(
                  "block px-3",
                  line.kind === "same" && "text-ink-secondary",
                  line.kind === "removed" && "bg-surface-raised text-ink-secondary line-through",
                  line.kind === "added" && "bg-surface-raised text-ink",
                )}
              >
                <span aria-hidden="true" className="mr-2 inline-block w-2 text-ink-muted select-none">
                  {DIFF_MARKS[line.kind]}
                </span>
                {line.text === "" ? " " : line.text}
              </span>
            );
          })}
        </pre>
      )}
    </div>
  );
}

function RawTabButton({
  isSelected,
  onClick,
  children,
}: {
  isSelected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={isSelected}
      onClick={onClick}
      className={cn(
        "flex h-8 items-center gap-1.5 border-b-2 px-2 text-data whitespace-nowrap focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent motion-safe:transition-colors",
        isSelected ? "border-accent font-medium text-ink" : "border-transparent text-ink-secondary hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function Count({ value }: { value: number }) {
  return <span className="text-label text-ink-muted tabular-nums">{formatCount(value)}자</span>;
}
