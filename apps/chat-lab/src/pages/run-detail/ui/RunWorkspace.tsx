import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import type { RunDetail } from "@/shared/api/client";
import { cn } from "@/shared/lib/cn";

import { useRunMetrics } from "../api/useRunMetrics";
import { useTurnDetail } from "../api/useTurnDetail";
import { useDetailKeys } from "../lib/useDetailKeys";
import { findMatches, stepMatch } from "../model/rawSearch";
import { describeRaw, dumpSourceLabel, dumpSources, pickDumpRecord } from "../model/rawSource";
import { readText } from "../model/recordFields";
import {
  dumpSourceText,
  INSPECTOR_TABS,
  resolveAttempt,
  resolveDumpSource,
  resolveTurn,
  type DumpSource,
  type InspectorTab,
  type Pane,
  type RawTab,
  type RunDetailSearch,
} from "../model/runDetailSearch";
import { attemptDeltas, buildTurnRows, seriesTones } from "../model/turnRows";
import { ConversationPane } from "./ConversationPane";
import { Inspector, type MetricsState } from "./Inspector";
import { IssueList } from "./IssueList";
import { PaneBar } from "./PaneBar";
import { RawPane } from "./RawPane";
import { StateTimeline } from "./StateTimeline";
import { TurnList } from "./TurnList";

type RunWorkspaceProps = {
  runId: string;
  detail: RunDetail;
  notice: ReactNode;
  isIssuesOpen: boolean;
  onCloseIssues: () => void;
};

/**
 * 런 상세 작업대 — 위 상태 타임라인 띠, 아래 턴 목록 272px │ 대화·원문 │ 호출 검사기 380px. 1280px 미만은 검사기를 대화·원문과
 * 갈아 끼우고, 1024px 미만은 세 칸 가운데 하나만 보인다(띠 아래 칸 바꾸기 줄). 고른 턴·시도·탭·칸·원문 출처는 주소에 있고(뒤로
 * 가기에 턴마다 쌓이지 않게 바꿔 적는다), 원문 검색어는 이 화면 안에만 둔다 — 턴을 옮겨도 같은 낱말을 이어 찾는다.
 */
export function RunWorkspace({ runId, detail, notice, isIssuesOpen, onCloseIssues }: RunWorkspaceProps) {
  const search = useSearch({ from: "/runs/$runId" });
  const navigate = useNavigate({ from: "/runs/$runId" });
  const metricsQuery = useRunMetrics(runId);
  const turn = resolveTurn(detail.turns, search.turn);
  const turnQuery = useTurnDetail(runId, turn);
  const turnDetail = turnQuery.data;
  const rows = useMemo(() => buildTurnRows(detail.turns, detail.series), [detail.turns, detail.series]);
  const tones = useMemo(() => seriesTones(detail.series), [detail.series]);
  const turnNumbers = useMemo(() => detail.turns.map((summary) => summary.turn), [detail.turns]);
  const knownTurns = useMemo(() => new Set(turnNumbers), [turnNumbers]);
  const turnIndex = turn === undefined ? -1 : turnNumbers.indexOf(turn);
  // 턴을 옮기는 동안 상세 칸은 앞 턴 내용을 흐리게 들고 있다 — 요약·행은 고른 턴이 아니라 지금 그려진 상세의 턴으로 찾는다.
  const shownIndex = turnDetail === undefined ? -1 : turnNumbers.indexOf(turnDetail.turn);
  const summary = detail.turns[shownIndex];
  const row = rows[shownIndex];
  const metricsState = describeMetricsState(metricsQuery);

  const attemptIndex = turnDetail ? resolveAttempt(turnDetail.attempts, search.attempt) : undefined;
  const attempt = turnDetail?.attempts.find((candidate) => candidate.index === attemptIndex);
  const source: DumpSource = turnDetail
    ? resolveDumpSource(search.dump, {
        earlier: turnDetail.earlierGenerationDumps.length,
        judgment: turnDetail.judgmentDumps.length,
        background: turnDetail.backgroundDumps.length,
      })
    : { kind: "generation" };
  const rawTab: RawTab = search.raw ?? "prompt";
  const inspectorTab: InspectorTab = search.inspector ?? "calls";
  const pane: Pane = search.pane ?? "conversation";

  const rawField = rawTab === "instruction" ? "systemInstruction" : "prompt";
  const rawView = turnDetail ? describeRaw(turnDetail, attempt, source, rawField) : undefined;
  const rawText = rawView?.kind === "text" ? rawView.text : "";

  const [query, setQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const [isRawFolded, setIsRawFolded] = useState(false);
  const matches = useMemo(() => findMatches(rawText, query), [rawText, query]);
  const currentMatch = matches.length === 0 ? -1 : Math.min(matchIndex, matches.length - 1);

  const searchRef = useRef<HTMLInputElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const turnListRef = useRef<HTMLOListElement>(null);

  const updateSearch = useCallback(
    (patch: Partial<RunDetailSearch>) => {
      void navigate({ search: (previous) => ({ ...previous, ...patch }), replace: true });
    },
    [navigate],
  );

  // 턴 목록 행에 넘기는 콜백은 렌더마다 새로 만들지 않는다 — 행이 메모되어 있다.
  const selectTurn = useCallback(
    (next: number) => updateSearch({ turn: next, attempt: undefined, dump: undefined }),
    [updateSearch],
  );

  function moveTurn(step: 1 | -1) {
    const next = turnNumbers[Math.min(turnNumbers.length - 1, Math.max(0, turnIndex + step))];
    if (next === undefined || next === turn) return;
    // 포커스를 새 행으로 옮기면 그 행이 포커스를 받으며 스스로 골라진다. 행이 보이지 않아 포커스가 가지 않으면 직접 고른다.
    if (!revealTurnRow(turnListRef.current, next)) selectTurn(next);
  }

  function moveAttempt(step: 1 | -1) {
    if (!turnDetail || turnQuery.isPlaceholderData) return;
    const attempts = turnDetail.attempts;
    const index = attempts.findIndex((candidate) => candidate.index === attemptIndex);
    const next = attempts[Math.min(attempts.length - 1, Math.max(0, index + step))];
    if (next !== undefined) updateSearch({ attempt: next.index });
  }

  function openDump(next: DumpSource) {
    updateSearch({ dump: dumpSourceText(next), raw: "prompt", pane: "conversation" });
    setIsRawFolded(false);
  }

  function focusSearch() {
    if (rawTab === "compare" || pane !== "conversation") updateSearch({ raw: rawTab === "compare" ? "prompt" : rawTab, pane: "conversation" });
    setIsRawFolded(false);
    // 칸이 펼쳐지고(접힘·다른 탭·좁은 화면의 다른 칸) 그려진 다음에 포커스한다.
    window.requestAnimationFrame(() => {
      searchRef.current?.focus();
      searchRef.current?.select();
    });
  }

  function handleQueryChange(next: string) {
    setQuery(next);
    setMatchIndex(0);
  }

  function handleStepMatch(step: 1 | -1) {
    if (matches.length === 0) return;
    setMatchIndex(stepMatch(currentMatch, matches.length, step));
  }

  function handleCloseSearch() {
    setQuery("");
    searchRef.current?.blur();
  }

  useDetailKeys({
    onMoveTurn: moveTurn,
    onMoveAttempt: moveAttempt,
    onFocusSearch: focusSearch,
    onStepMatch: handleStepMatch,
    onInspectorTab: (index) => {
      const next = INSPECTOR_TABS[index];
      if (next !== undefined) updateSearch({ inspector: next, pane: "inspector" });
    },
    onFocusTimeline: () => timelineRef.current?.focus(),
    onEscape: () => {
      if (isIssuesOpen) onCloseIssues();
      else if (query !== "") setQuery("");
    },
  });

  const isStale = turnQuery.isPlaceholderData;
  const sourceOptions = turnDetail
    ? dumpSources(turnDetail).map((candidate) => ({
        value: dumpSourceText(candidate),
        label: dumpSourceLabel(turnDetail, attempt, candidate),
      }))
    : [];
  const sourceRecord = turnDetail ? pickDumpRecord(turnDetail, attempt, source) : undefined;

  return (
    <div className="relative flex h-full flex-col">
      {notice}
      <StateTimeline
        turns={turnNumbers}
        markers={detail.markers}
        selectedTurn={turn}
        timelineRef={timelineRef}
        onSelectTurn={selectTurn}
      />
      <PaneBar
        pane={pane}
        turn={turn}
        turnIndex={turnIndex}
        turnCount={turnNumbers.length}
        onPaneChange={(next) => updateSearch({ pane: next })}
        onMoveTurn={moveTurn}
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[17rem_minmax(0,1fr)] xl:grid-cols-[17rem_minmax(0,1fr)_23.75rem]">
        <section
          aria-label="턴 목록"
          className={cn(
            "min-h-0 overflow-auto border-r border-border bg-surface lg:block",
            pane === "turns" ? "block" : "hidden",
          )}
        >
          <TurnList
            rows={rows}
            selectedTurn={turn}
            scored={metricsQuery.data?.scored}
            listRef={turnListRef}
            onSelectTurn={selectTurn}
          />
        </section>

        <section
          aria-label="대화·원문"
          aria-busy={isStale || undefined}
          className={cn(
            "min-h-0 flex-col bg-surface xl:flex",
            pane === "conversation" ? "flex" : "hidden",
            pane === "inspector" ? "lg:hidden" : "lg:flex",
          )}
        >
          {turnDetail === undefined ? (
            <TurnPending
              hasTurns={turn !== undefined}
              isError={turnQuery.isError}
              onRetry={() => void turnQuery.refetch()}
            />
          ) : (
            <>
              <div
                className={cn(
                  "min-h-0 overflow-auto",
                  isRawFolded ? "flex-1" : "max-h-[55%] shrink-0",
                  isStale && "opacity-50",
                )}
              >
                <ConversationPane
                  turn={turnDetail.turn}
                  turnDetail={turnDetail}
                  attempt={attempt}
                  deltas={attemptDeltas(row, attempt, tones)}
                  isStale={isStale}
                  onSelectAttempt={(index) => updateSearch({ attempt: index })}
                />
              </div>
              <div className={cn("flex min-h-0 flex-col", isRawFolded ? "shrink-0" : "flex-1", isStale && "opacity-50")}>
                <RawPane
                  turn={turnDetail.turn}
                  tab={rawTab}
                  onTabChange={(next) => updateSearch({ raw: next })}
                  sourceOptions={sourceOptions}
                  sourceValue={dumpSourceText(source)}
                  source={source}
                  onSourceChange={(value) => updateSearch({ dump: value })}
                  view={rawView ?? { kind: "noDumpForAttempt" }}
                  promptLength={readText(sourceRecord, "prompt")?.length}
                  instructionLength={readText(sourceRecord, "systemInstruction")?.length}
                  earlierPrompts={turnDetail.earlierGenerationDumps.map((dump) => readText(dump, "prompt"))}
                  query={query}
                  onQueryChange={handleQueryChange}
                  matches={matches}
                  currentMatch={currentMatch}
                  onStepMatch={handleStepMatch}
                  onCloseSearch={handleCloseSearch}
                  searchRef={searchRef}
                  isFolded={isRawFolded}
                  onToggleFold={() => setIsRawFolded((previous) => !previous)}
                />
              </div>
            </>
          )}
        </section>

        <aside
          aria-label="호출 검사기"
          aria-busy={isStale || undefined}
          className={cn(
            "min-h-0 overflow-auto border-l border-border bg-surface xl:block",
            pane === "inspector" ? "block lg:block" : "hidden lg:hidden",
            isStale && "opacity-50",
          )}
        >
          {turnDetail !== undefined && (
            <Inspector
              tab={inspectorTab}
              onTabChange={(next) => updateSearch({ inspector: next })}
              detail={detail}
              summary={summary}
              turnDetail={turnDetail}
              attempt={attempt}
              metrics={metricsState}
              onRetryMetrics={() => void metricsQuery.refetch()}
              knownTurns={knownTurns}
              isStale={isStale}
              onOpenDump={openDump}
              onSelectTurn={selectTurn}
            />
          )}
        </aside>
      </div>
      {isIssuesOpen && (
        <IssueList
          mismatches={detail.mismatches}
          cautions={detail.cautions}
          knownTurns={knownTurns}
          onSelectTurn={selectTurn}
          onClose={onCloseIssues}
        />
      )}
    </div>
  );
}

type TurnPendingProps = {
  hasTurns: boolean;
  isError: boolean;
  onRetry: () => void;
};

/**
 * 턴 상세가 아직 없을 때 가운데 칸 — 턴이 없는 런, 첫 턴 상세를 받지 못함, 받는 중. 턴을 옮기는 동안은 앞 턴 내용이 흐리게 남아
 * 이 자리가 보이지 않는다.
 */
function TurnPending({ hasTurns, isError, onRetry }: TurnPendingProps) {
  if (!hasTurns) {
    return <p className="px-4 py-6 text-body text-ink-secondary">이 런에는 턴이 없다 — 드라이버 로그에 턴 줄이 하나도 없다.</p>;
  }
  if (isError) {
    return (
      <div className="space-y-2 px-4 py-6 text-body text-ink-secondary">
        <p>이 턴의 상세를 받지 못했다.</p>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-sm text-ink-secondary underline underline-offset-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          다시 받기
        </button>
      </div>
    );
  }
  return (
    <p role="status" className="px-4 py-6 text-body text-ink-muted">
      턴 상세를 받는 중이다.
    </p>
  );
}

/**
 * 런 지표 응답의 상태. 한 번 받은 지표는 뒤이은 다시 받기가 실패해도 그대로 쓴다. 실패 뒤 다시 받는 중이면 받는 중이다.
 */
function describeMetricsState(query: ReturnType<typeof useRunMetrics>): MetricsState {
  if (query.data !== undefined) return { status: "ready", metrics: query.data };
  if (query.isError && !query.isFetching) return { status: "failed" };
  return { status: "loading" };
}

/**
 * 턴 행을 목록 스크롤 안에 들이고 그 행으로 포커스를 옮긴다(목록 화면의 j/k 와 같은 규칙). 포커스가 실제로 그 행에 갔으면 참 —
 * 좁은 화면에서 목록 칸이 숨어 있으면 포커스가 가지 않아 거짓이다.
 */
function revealTurnRow(list: HTMLOListElement | null, turn: number): boolean {
  const target = list?.querySelector<HTMLElement>(`[data-turn="${turn}"]`);
  if (!target) return false;
  target.focus({ preventScroll: true });
  if (document.activeElement !== target) return false;
  target.scrollIntoView({ block: "nearest" });
  return true;
}
