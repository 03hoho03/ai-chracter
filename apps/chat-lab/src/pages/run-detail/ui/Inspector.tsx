import type { ReactNode } from "react";

import type {
  AttemptDetail,
  CallCostView,
  RunDetail,
  RunMetrics,
  TurnDetail,
  TurnSummary,
} from "@/shared/api/client";
import { COST_GAP_TEXT, RECORD_GAP_TEXT, runRecordGap, type RecordGap } from "@/shared/api/recordGap";
import { assertNever } from "@/shared/lib/assertNever";
import { cn } from "@/shared/lib/cn";
import { formatCount, formatMs, formatUsd } from "@/shared/lib/formatNumber";

import { attemptCalls, generationCardCount, type AttemptCalls, type JudgmentSite } from "../model/callGroups";
import {
  BOOLEAN_FLAG_KEYS,
  BOOLEAN_FLAG_LABELS,
  CAUTION_LABELS,
  describePreviousFrom,
  INSPECTOR_TAB_OPTIONS,
  MISMATCH_LABELS,
  REPLY_FLAG_LABELS,
} from "../model/detailLabels";
import { readNumber, readRecord, readRecords, readText } from "../model/recordFields";
import { recordLimitText } from "../model/recordLimits";
import { flaggedTurns, type RunFlagKey } from "../model/runFlags";
import { describeRunFocus, type FocusTone } from "../model/runFocus";
import type { DumpSource, InspectorTab } from "../model/runDetailSearch";
import { TokenBar } from "./TokenBar";

/** 런 지표 응답의 상태 — 받기 전·실패에는 플래그 수를 모르므로 "없음"과 갈라 적는다. */
export type MetricsState = { status: "loading" } | { status: "failed" } | { status: "ready"; metrics: RunMetrics };

type InspectorProps = {
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  detail: RunDetail;
  summary: TurnSummary | undefined;
  turnDetail: TurnDetail;
  attempt: AttemptDetail | undefined;
  metrics: MetricsState;
  onRetryMetrics: () => void;
  /** 이 런에 있는 턴 번호. 불일치가 가리키는 턴이 여기 없으면(건너뛴 번호·짝 없는 줄) 고를 수 없다. */
  knownTurns: ReadonlySet<number>;
  /** 턴을 옮기는 동안 앞 턴 상세를 흐리게 들고 있다 — 그동안 원문 열기는 앞 턴의 덤프를 새 턴에 적용하게 되므로 막는다. */
  isStale: boolean;
  onOpenDump: (source: DumpSource) => void;
  onSelectTurn: (turn: number) => void;
};

const FOCUS_TONE_CLASSES = {
  danger: "text-danger",
  warn: "text-warn",
  quiet: "text-ink-secondary",
} as const satisfies Record<FocusTone, string>;

/** 런 요약의 응답 플래그 줄 — 이 순서로 적는다. 이름은 지표 탭의 턴 칸과 같다. */
const RUN_FLAG_ROWS = [
  ...BOOLEAN_FLAG_KEYS.map((key) => ({ key, label: BOOLEAN_FLAG_LABELS[key] })),
  { key: "broken", label: REPLY_FLAG_LABELS.broken },
  { key: "brackets", label: REPLY_FLAG_LABELS.brackets },
] as const satisfies ReadonlyArray<{ key: RunFlagKey; label: string }>;

/** 런 요약의 플래그 수 — 측정 서버가 센 값을 그대로 읽는다. */
const RUN_FLAG_COUNTS = {
  truncated: (metrics) => metrics.truncated,
  selfCopy: (metrics) => metrics.selfCopy,
  labelLeak: (metrics) => metrics.labelLeak,
  userTurn: (metrics) => metrics.userTurn,
  solicit: (metrics) => metrics.solicit,
  ignored: (metrics) => metrics.ignored,
  sceneOpen: (metrics) => metrics.sceneOpen,
  broken: (metrics) => metrics.broken,
  brackets: (metrics) => metrics.brackets,
} as const satisfies Record<RunFlagKey, (metrics: RunMetrics) => number>;

/** 턴 원가가 하한일 때 붙이는 까닭 — 측정 서버가 하한으로 보는 조건 그대로다. */
const LOWER_BOUND_NOTE = "단가표에 없는 호출이나 입력 토큰이 기록되지 않은 호출이 있어 실제 원가는 이보다 크거나 같다";

/**
 * 오른쪽 호출 검사기 — 호출(생성·판정 call_site 별·백그라운드) · 기억 · 라우팅 · 지표. 단축키 `1`~`4` 가 탭 순서다. 값이 비면 0 이나
 * 대시로 덮지 않고 "기록 없음"·"내보내기 필요"로 말하고, 측정 서버가 준 기록 한계 문장은 그 값이 있어야 할 자리(판정·백그라운드
 * 묶음 머리 — 카드마다 같은 까닭이라 한 번, 턴 원가 칸)에 그대로 둔다.
 */
export function Inspector(props: InspectorProps) {
  const { tab, onTabChange, detail, attempt } = props;
  const rows = attempt?.chatTurns ?? [];
  const calls = rows.flatMap((row) => row.calls);
  const view = attemptCalls(
    calls,
    { judgment: props.turnDetail.judgmentDumps, backgroundCount: props.turnDetail.backgroundDumps.length },
    attempt?.selected !== false,
  );
  const recallCount = rows.reduce((count, row) => count + readRecords(row.row, "memory_recall").length, 0);
  const factCount = rows.reduce((count, row) => count + readRecords(row.row, "memory_facts").length, 0);
  const routeCount = rows.reduce((count, row) => count + readRecords(row.row, "stage_routes").length, 0);
  // 런 전체에 턴 기록이 비면(파일이 없거나 이전 형식이라 잇지 않음) 호출 칸이 비어 있어 덤프 줄만 센 수가 되므로 개수를 적지
  // 않는다(기억·라우팅과 같다).
  const hasRecords = runRecordGap(detail.run) === undefined;
  const counts = {
    calls: hasRecords ? view.cardCount : undefined,
    memory: hasRecords ? recallCount + factCount : undefined,
    routing: hasRecords ? routeCount : undefined,
    metrics: undefined,
  } satisfies Record<InspectorTab, number | undefined>;

  return (
    <>
      <div role="tablist" aria-label="호출 검사기" className="sticky top-0 z-10 flex h-8 items-stretch border-b border-border bg-surface px-1">
        {INSPECTOR_TAB_OPTIONS.map(({ tab: candidate, label }, index) => (
          <button
            key={candidate}
            type="button"
            role="tab"
            aria-selected={candidate === tab}
            title={`${label} (${index + 1})`}
            onClick={() => onTabChange(candidate)}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-2.5 text-data whitespace-nowrap focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent motion-safe:transition-colors",
              candidate === tab ? "border-accent font-medium text-ink" : "border-transparent text-ink-secondary hover:text-ink",
            )}
          >
            {label}
            {counts[candidate] !== undefined && (
              <span className="text-label text-ink-muted tabular-nums">{formatCount(counts[candidate])}</span>
            )}
          </button>
        ))}
      </div>
      {/* 흐린 앞 턴 상세 안의 버튼(원문 보기 등)을 한꺼번에 막는다 — 누르면 앞 턴의 덤프 순번이 새 턴에 적용된다. 막힌 fieldset 은
          안의 버튼을 모두 비활성으로 만든다. */}
      <fieldset disabled={props.isStale} className="min-w-0">
        <InspectorBody {...props} view={view} />
      </fieldset>
    </>
  );
}

function InspectorBody(props: InspectorProps & { view: AttemptCalls }) {
  switch (props.tab) {
    case "calls":
      return <CallsTab {...props} />;
    case "memory":
      return <MemoryTab {...props} />;
    case "routing":
      return <RoutingTab {...props} />;
    case "metrics":
      return <MetricsTab {...props} />;
    default:
      return assertNever(props.tab);
  }
}

function CallsTab({ detail, summary, turnDetail, attempt, view, onOpenDump }: InspectorProps & { view: AttemptCalls }) {
  const { groups } = view;
  const gap = runRecordGap(detail.run);
  const generationDump = attempt?.generationDump ?? undefined;
  const tokenAbsence = gap === undefined ? "이 시도에 붙은 턴 기록 행 없음" : RECORD_GAP_TEXT[gap];
  const limits = turnDetail.recordLimits;
  const exportLimit = recordLimitText(limits, "exportNeeded");
  const responseLimit = recordLimitText(limits, "judgmentResponse");
  const latencyLimit = recordLimitText(limits, "judgmentLatency");
  const backgroundLimit = recordLimitText(limits, "backgroundTokens");
  const backgroundDumps = turnDetail.backgroundDumps.slice(0, view.backgroundDumpCount);
  const backgroundCount = groups.background.length + backgroundDumps.length;
  const selectedAttempt = turnDetail.attempts.find((candidate) => candidate.selected)?.index;

  return (
    <div className="pb-4">
      {summary !== undefined && (
        <div className="border-b border-border px-3 py-2">
          <p className="flex items-center gap-2 text-data text-ink-secondary">
            이 턴 원가
            <span className="ml-auto tabular-nums">
              <TurnCost summary={summary} gap={gap} />
            </span>
          </p>
          {exportLimit !== undefined && <RecordLimitNote className="mt-1.5">{exportLimit}</RecordLimitNote>}
        </div>
      )}

      <GroupTitle count={generationCardCount(groups)}>생성</GroupTitle>
      {groups.generation.map((call, index) => (
        // 턴 기록 행의 호출 칸 순서 그대로이고 바뀌지 않는다.
        <CallCard key={index} call={call} onOpenRaw={generationDump ? () => onOpenDump({ kind: "generation" }) : undefined} />
      ))}
      {groups.generation.length === 0 && (
        <DumpOnlyCard
          callSite="chat_generate"
          model={readText(generationDump, "model")}
          promptLength={readText(generationDump, "prompt")?.length}
          tokens={tokenAbsence}
          onOpenRaw={generationDump ? () => onOpenDump({ kind: "generation" }) : undefined}
        />
      )}

      <GroupTitle count={groups.judgment.length} note="call_site 별">
        판정
      </GroupTitle>
      {view.heldJudgmentDumps > 0 && (
        <HeldTurnDumps count={view.heldJudgmentDumps} kind="판정" selectedAttempt={selectedAttempt} />
      )}
      {groups.judgment.length === 0 && view.heldJudgmentDumps === 0 && (
        <p className="px-3 py-2 text-data text-ink-muted">이 턴의 판정 덤프 줄·판정 호출 기록 없음</p>
      )}
      {groups.judgment.length > 0 && (responseLimit !== undefined || latencyLimit !== undefined) && (
        // 판정 응답·지연 문장은 이 턴의 판정 카드 모두에 같은 까닭이라 카드마다 되풀이하지 않고 묶음 머리에 한 번 둔다.
        <div className="space-y-1.5 px-3 pb-1">
          {responseLimit !== undefined && <RecordLimitNote>{responseLimit}</RecordLimitNote>}
          {latencyLimit !== undefined && <RecordLimitNote>{latencyLimit}</RecordLimitNote>}
        </div>
      )}
      {groups.judgment.map((site) => (
        <JudgmentSiteCard key={site.callSite} site={site} turnDetail={turnDetail} tokens={tokenAbsence} onOpenDump={onOpenDump} />
      ))}

      <GroupTitle count={backgroundCount}>백그라운드</GroupTitle>
      {view.heldBackgroundDumps > 0 && (
        <HeldTurnDumps count={view.heldBackgroundDumps} kind="백그라운드" selectedAttempt={selectedAttempt} />
      )}
      {backgroundCount === 0 && view.heldBackgroundDumps === 0 && (
        <p className="px-3 py-2 text-data text-ink-muted">이 턴에 둔 백그라운드 덤프 줄 없음</p>
      )}
      {backgroundDumps.length > 0 && backgroundLimit !== undefined && (
        // 백그라운드 토큰 문장은 이 턴의 백그라운드 덤프 카드 모두에 같은 까닭이라 카드마다 되풀이하지 않고 묶음 머리에 한 번 둔다.
        <div className="px-3 pb-1">
          <RecordLimitNote>{backgroundLimit}</RecordLimitNote>
        </div>
      )}
      {groups.background.map((call, index) => (
        // 턴 기록 행의 호출 칸 순서 그대로이고 바뀌지 않는다.
        <CallCard key={index} call={call} />
      ))}
      {backgroundDumps.map((dump, index) => (
        <div
          // 그 턴에 붙은 순서 그대로이고 바뀌지 않는다.
          key={index}
          className="border-b border-border px-3 py-2.5"
        >
          <CallHead
            callSite={readText(dump.record, "callSite") ?? "call_site 없음"}
            model={readText(dump.record, "model")}
            right={<span className="text-ink-muted">기록 없음</span>}
          />
          <p className="mt-1 flex flex-wrap gap-x-3 text-label text-ink-muted tabular-nums">
            <span title="백그라운드 줄의 턴 자리는 추정이다 — 응답 뒤에 돌아 다음 턴 생성 줄보다 늦게 쓰일 수 있다" className="text-warn">
              배치 추정
            </span>
            <span>{dump.placement === "turnField" ? "턴 칸 기준" : "바로 앞 생성 줄 기준"}</span>
            {readText(dump.record, "prompt") !== undefined && (
              <span>프롬프트 {formatCount(readText(dump.record, "prompt")?.length ?? 0)}자</span>
            )}
            <span>토큰·원가 기록 없음</span>
          </p>
          <OpenRawButton onClick={() => onOpenDump({ kind: "background", index: index + 1 })} />
        </div>
      ))}

      {groups.other.length > 0 && (
        <>
          <GroupTitle count={groups.other.length}>그 밖</GroupTitle>
          {groups.other.map((call, index) => (
            // 턴 기록 행의 호출 칸 순서 그대로이고 바뀌지 않는다.
            <CallCard key={index} call={call} />
          ))}
        </>
      )}
    </div>
  );
}

/**
 * 턴 원가 칸. 런 전체가 비는 까닭(이전 형식, 턴 기록 파일 없음)과, 파일은 있지만 이 턴에 붙은 행이 없는 턴을 갈라 적는다 — 어느
 * 것도 `$0.0000` 이 아니다.
 */
function TurnCost({ summary, gap }: { summary: TurnSummary; gap: RecordGap | undefined }) {
  if (summary.costUsd === null) {
    return <span className="text-ink-muted">{gap === undefined ? "턴 기록 행 없음" : COST_GAP_TEXT[gap]}</span>;
  }
  return (
    <data value={summary.costUsd} title={summary.costIsLowerBound ? LOWER_BOUND_NOTE : undefined} className="text-ink">
      {summary.costIsLowerBound && <span className="text-ink-muted">≥ </span>}
      {formatUsd(summary.costUsd)}
    </data>
  );
}

/**
 * 고른 시도가 아닌 시도의 판정·백그라운드 묶음 자리. 그 덤프 줄은 시도가 아니라 턴에 붙어 이 시도의 것이라고 말할 수 없어, 카드를
 * 그리지 않고(탭 숫자에도 세지 않는다) 어디서 보는지를 적는다.
 */
function HeldTurnDumps({ count, kind, selectedAttempt }: { count: number; kind: string; selectedAttempt: number | undefined }) {
  const where = selectedAttempt === undefined ? "고른 시도" : `고른 시도(시도 ${selectedAttempt})`;
  return (
    <p className="px-3 py-2 text-data text-ink-muted">
      이 턴의 {kind} 덤프 줄 {formatCount(count)}개는 시도가 아니라 턴에 붙어 {where}에서 보인다
    </p>
  );
}

type JudgmentSiteCardProps = {
  site: JudgmentSite;
  turnDetail: TurnDetail;
  tokens: string;
  onOpenDump: (source: DumpSource) => void;
};

function JudgmentSiteCard({ site, turnDetail, tokens, onOpenDump }: JudgmentSiteCardProps) {
  const firstDump = site.dumpIndexes[0] === undefined ? undefined : turnDetail.judgmentDumps[site.dumpIndexes[0] - 1];
  if (site.calls.length === 0) {
    return (
      <DumpOnlyCard
        callSite={site.callSite}
        model={readText(firstDump, "model")}
        promptLength={readText(firstDump, "prompt")?.length}
        tokens={tokens}
        dumpIndexes={site.dumpIndexes}
        onOpenIndex={(index) => onOpenDump({ kind: "judgment", index })}
      />
    );
  }
  return (
    <>
      {site.calls.map((call, index) => (
        // 턴 기록 행의 호출 칸 순서 그대로이고 바뀌지 않는다.
        <CallCard key={index} call={call}>
          {index === site.calls.length - 1 && (
            <DumpLinks dumpIndexes={site.dumpIndexes} onOpenIndex={(dumpIndex) => onOpenDump({ kind: "judgment", index: dumpIndex })} />
          )}
        </CallCard>
      ))}
    </>
  );
}

type CallCardProps = {
  call: CallCostView;
  onOpenRaw?: () => void;
  children?: ReactNode;
};

function CallCard({ call, onOpenRaw, children }: CallCardProps) {
  return (
    <div className="border-b border-border px-3 py-2.5">
      <CallHead callSite={call.callSite} model={call.model} right={<CallUsd call={call} />} />
      <TokenBar call={call} />
      <p className="mt-1 flex flex-wrap gap-x-3 text-label text-ink-muted tabular-nums">
        <span>
          사고 {call.thoughtsTokens === null ? "기록 없음" : <span className="text-ink-secondary">{formatCount(call.thoughtsTokens)}</span>}
        </span>
        <span>
          첫 토큰 {call.firstTokenMs === null ? "기록 없음" : <span className="text-ink-secondary">{formatMs(call.firstTokenMs)}</span>}
        </span>
        {call.streamFirstTokenMs !== null && (
          <span>
            스트림 첫 토큰 <span className="text-ink-secondary">{formatMs(call.streamFirstTokenMs)}</span>
          </span>
        )}
      </p>
      {onOpenRaw !== undefined && <OpenRawButton onClick={onOpenRaw} />}
      {children}
    </div>
  );
}

/**
 * 호출 하나의 원가 칸. 원가가 비면 까닭이 둘이다 — 입력 토큰이 기록되지 않았거나(그 값은 이 호출의 원가가 아니다), 모델이
 * 단가표에 없다.
 */
function CallUsd({ call }: { call: CallCostView }) {
  if (call.usd !== null) return <span className="text-ink">{formatUsd(call.usd)}</span>;
  return <span className="text-ink-muted">{call.missingTokens ? "토큰 기록 없음" : "단가표에 없음"}</span>;
}

type DumpOnlyCardProps = {
  callSite: string;
  model: string | undefined;
  promptLength: number | undefined;
  tokens: string;
  onOpenRaw?: () => void;
  dumpIndexes?: ReadonlyArray<number>;
  onOpenIndex?: (index: number) => void;
};

/** 턴 기록의 호출 칸 없이 덤프 줄만 있는 호출 — 토큰 칸 자리에 왜 없는지를 적는다. */
function DumpOnlyCard({ callSite, model, promptLength, tokens, onOpenRaw, dumpIndexes, onOpenIndex }: DumpOnlyCardProps) {
  return (
    <div className="border-b border-border px-3 py-2.5">
      <CallHead callSite={callSite} model={model} right={<span className="text-ink-muted">{tokens}</span>} />
      <p className="mt-1 flex flex-wrap gap-x-3 text-label text-ink-muted tabular-nums">
        {promptLength !== undefined && <span>프롬프트 {formatCount(promptLength)}자</span>}
        <span>토큰 {tokens}</span>
      </p>
      {onOpenRaw !== undefined && <OpenRawButton onClick={onOpenRaw} />}
      {dumpIndexes !== undefined && onOpenIndex !== undefined && <DumpLinks dumpIndexes={dumpIndexes} onOpenIndex={onOpenIndex} />}
    </div>
  );
}

function DumpLinks({ dumpIndexes, onOpenIndex }: { dumpIndexes: ReadonlyArray<number>; onOpenIndex: (index: number) => void }) {
  if (dumpIndexes.length === 0) return <p className="mt-1 text-label text-ink-muted">이 call_site 의 덤프 줄 없음</p>;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {dumpIndexes.map((index, order) => (
        <button
          key={index}
          type="button"
          onClick={() => onOpenIndex(index)}
          className="h-6 rounded-sm px-1.5 text-label text-ink-secondary enabled:hover:bg-surface-raised enabled:hover:text-ink disabled:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent"
        >
          원문 보기{dumpIndexes.length > 1 ? ` ${order + 1}` : ""}
        </button>
      ))}
    </div>
  );
}

function OpenRawButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-1.5 h-6 rounded-sm px-1.5 text-label text-ink-secondary enabled:hover:bg-surface-raised enabled:hover:text-ink disabled:text-ink-muted focus-visible:outline-2 focus-visible:outline-accent"
    >
      원문 보기
    </button>
  );
}

function CallHead({ callSite, model, right }: { callSite: string; model: string | undefined; right: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="min-w-0 truncate font-mono text-data font-semibold text-ink">{callSite}</span>
      {model !== undefined && <span className="min-w-0 truncate font-mono text-label text-ink-secondary">{model}</span>}
      <span className="ml-auto shrink-0 text-data tabular-nums">{right}</span>
    </div>
  );
}

function MemoryTab({ detail, turnDetail, attempt }: InspectorProps) {
  const rows = attempt?.chatTurns ?? [];
  const recall = rows.flatMap((row) => readRecords(row.row, "memory_recall"));
  const facts = rows.flatMap((row) => readRecords(row.row, "memory_facts"));
  const snapshot = turnDetail.memorySnapshot;
  const absence = rowAbsence(runRecordGap(detail.run), rows.length);

  return (
    <div className="space-y-4 px-3 py-3">
      <section aria-label="회상한 장면 기억">
        <SectionTitle count={absence === undefined ? recall.length : undefined}>회상한 장면 기억</SectionTitle>
        <RowListState
          absence={absence}
          count={recall.length}
          emptyText="없음 — 이 턴 프롬프트에 실은 장면 기억이 없다(회상을 쓰지 않은 턴 포함)"
        >
          <table className="mt-1 w-full text-data tabular-nums">
            <thead>
              <tr className="border-b border-border-strong text-left text-label text-ink-muted">
                <th className="py-1 pr-2 font-medium">순위</th>
                <th className="py-1 pr-2 font-medium">장면 id</th>
                <th className="py-1 pr-2 text-right font-medium">점수</th>
                <th className="py-1 text-right font-medium">글자</th>
              </tr>
            </thead>
            <tbody>
              {recall.map((entry, index) => (
                // 턴 기록에 실린 순서 그대로이고 바뀌지 않는다.
                <tr key={index} className="h-7 border-b border-border">
                  <td className="pr-2">{readNumber(entry, "rank") ?? <Missing />}</td>
                  <td className="max-w-0 truncate pr-2 font-mono text-label" title={readText(entry, "episodeId")}>
                    {readText(entry, "episodeId") ?? "id 없음"}
                  </td>
                  <td className="pr-2 text-right">{formatScore(readNumber(entry, "score"))}</td>
                  <td className="text-right">{formatOptionalCount(readNumber(entry, "chars"))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </RowListState>
      </section>

      <section aria-label="실은 사실 기억">
        <SectionTitle count={absence === undefined ? facts.length : undefined}>실은 사실 기억</SectionTitle>
        <RowListState absence={absence} count={facts.length} emptyText="없음 — 이 턴 프롬프트에 실은 사실 기억이 없다">
          <ul className="mt-1 text-data">
            {facts.map((entry, index) => (
              // 턴 기록에 실린 줄 순서 그대로이고 바뀌지 않는다.
              <li key={index} className="flex h-7 items-center gap-2 border-b border-border">
                <span className="min-w-0 flex-1 truncate font-mono text-label" title={readText(entry, "factId")}>
                  {readText(entry, "factId") ?? "id 없음"}
                </span>
                <span className="shrink-0 text-ink-secondary tabular-nums">{formatOptionalCount(readNumber(entry, "chars"))}</span>
              </li>
            ))}
          </ul>
        </RowListState>
      </section>

      <section aria-label="기억 스냅숏">
        <SectionTitle>기억 스냅숏</SectionTitle>
        {snapshot === null ? (
          <Absent>{detail.run.hasSnapshots ? "이 턴 이하의 기억 스냅숏이 없다" : "이 묶음에는 스냅숏 파일이 없다"}</Absent>
        ) : (
          <div className="mt-1 space-y-2 text-data">
            <p className="text-ink-secondary">
              {turnDetail.memorySnapshotChangedHere
                ? "이 턴을 보내기 직전에 노트·요약이 바뀌었다."
                : `턴 ${readNumber(snapshot, "turn") ?? "?"} 에 적힌 스냅숏 — 이 턴까지 바뀌지 않았다.`}
            </p>
            <SnapshotText label="노트" text={readText(snapshot, "note")} length={readNumber(snapshot, "noteLen")} />
            <SnapshotText label="요약" text={readText(snapshot, "summary")} length={readNumber(snapshot, "summaryLen")} />
          </div>
        )}
      </section>
    </div>
  );
}

function SnapshotText({ label, text, length }: { label: string; text: string | undefined; length: number | undefined }) {
  if (text === undefined) {
    return (
      <p className="text-ink-muted">
        {label} — 원문 제외{length !== undefined && ` (${formatCount(length)}자)`}
      </p>
    );
  }
  return (
    <details className="group">
      <summary className="cursor-pointer text-ink-secondary hover:text-ink">
        {label} <span className="text-ink-muted tabular-nums">{formatCount(text.length)}자</span>
      </summary>
      <pre className="mt-1 rounded-md bg-surface-sunken p-2 font-mono text-mono whitespace-pre-wrap text-ink wrap-anywhere">
        {text === "" ? "(비어 있음)" : text}
      </pre>
    </details>
  );
}

function RoutingTab({ detail, attempt }: InspectorProps) {
  const rows = attempt?.chatTurns ?? [];
  const routes = rows.flatMap((row) => readRecords(row.row, "stage_routes"));
  const gap = runRecordGap(detail.run);
  if (gap !== undefined) return <div className="px-3 py-3"><Absent>{RECORD_GAP_TEXT[gap]}</Absent></div>;
  if (rows.length === 0) return <div className="px-3 py-3"><Absent>이 시도에 붙은 턴 기록 행 없음</Absent></div>;
  if (routes.length === 0) {
    return (
      <div className="px-3 py-3">
        <Absent>없음 — 이 행에는 단계별 모델 배정 기록이 없다(이 칸을 모르던 판이 쓴 행)</Absent>
      </div>
    );
  }
  return (
    <div className="px-3 py-3">
      <table className="w-full table-fixed text-data">
        <thead>
          <tr className="border-b border-border-strong text-left text-label text-ink-muted">
            <th className="w-[38%] py-1 pr-2 font-medium">단계</th>
            <th className="w-[34%] py-1 pr-2 font-medium">부른 모델</th>
            <th className="py-1 font-medium">출처</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route, index) => {
            const skipped = readRecord(route, "skipped");
            return (
              // 턴 기록에 실린 단계 순서 그대로이고 바뀌지 않는다.
              <tr key={index} className="border-b border-border align-top">
                <td className="py-1.5 pr-2 font-mono text-label wrap-anywhere">
                  {readText(route, "stage") ?? "단계 없음"}
                  {skipped !== undefined && (
                    <span className="block font-sans text-warn">건너뜀 · {readText(skipped, "reason") ?? "까닭 없음"}</span>
                  )}
                </td>
                <td className="py-1.5 pr-2 font-mono text-label text-ink-secondary wrap-anywhere">
                  {readText(route, "callModel") ?? "-"}
                  <span className="block text-ink-muted">{readText(route, "backend")}</span>
                </td>
                <td className="py-1.5 text-label text-ink-secondary wrap-anywhere">
                  {readText(route, "source") ?? "-"}
                  {readText(route, "sourceDetail") !== undefined && (
                    <span className="block font-mono text-ink-muted">{readText(route, "sourceDetail")}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MetricsTab({ detail, turnDetail, metrics: metricsState, onRetryMetrics, knownTurns, onSelectTurn }: InspectorProps) {
  const metrics = metricsState.status === "ready" ? metricsState.metrics : undefined;
  const focus = describeRunFocus(detail, metrics);
  const turnMetrics = turnDetail.metrics;

  return (
    <div className="space-y-4 px-3 py-3">
      <section aria-label="먼저 볼 것">
        <SectionTitle>먼저 볼 것</SectionTitle>
        <ul className="mt-1 space-y-1 text-data">
          {focus.map((line) => (
            <li key={line.text} className={FOCUS_TONE_CLASSES[line.tone]}>
              {line.text}
            </li>
          ))}
          {metricsState.status !== "ready" && (
            <li className="text-ink-muted">
              {metricsState.status === "loading"
                ? "런 지표를 받는 중이다 — 플래그 수는 받은 뒤에 적는다."
                : "런 지표를 받지 못해 플래그 수를 모른다 — 아래 런 요약에서 다시 받는다."}
            </li>
          )}
        </ul>
      </section>

      <section aria-label={`턴 ${turnDetail.turn} 지표`}>
        <SectionTitle>턴 {turnDetail.turn}</SectionTitle>
        {turnMetrics === null ? (
          <Absent>응답이 없는 턴이라 지표 표본에서 빠졌다</Absent>
        ) : (
          <dl className="mt-1 grid grid-cols-fields gap-x-3 gap-y-1 text-data">
            <Field label="길이">
              {formatCount(turnMetrics.flags.length)}자 · {formatCount(turnMetrics.flags.sentenceCount)}문장
              {turnMetrics.flags.statusBlockLength > 0 && (
                <span className="text-ink-muted"> · 상태창 {formatCount(turnMetrics.flags.statusBlockLength)}자 따로</span>
              )}
            </Field>
            {BOOLEAN_FLAG_KEYS.map((key) => (
              <Field key={key} label={BOOLEAN_FLAG_LABELS[key]}>
                {turnMetrics.flags[key] ? <span className="text-ink">예</span> : <span className="text-ink-muted">아니오</span>}
              </Field>
            ))}
            <Field label={REPLY_FLAG_LABELS.broken}>
              {turnMetrics.flags.broken === null ? <span className="text-ink-muted">아니오</span> : <span className="text-danger">{turnMetrics.flags.broken}</span>}
            </Field>
            <Field label={REPLY_FLAG_LABELS.brackets}>
              {turnMetrics.flags.brackets.length === 0 ? <span className="text-ink-muted">없음</span> : <span className="font-mono">{turnMetrics.flags.brackets.join(" ")}</span>}
            </Field>
            <Field label="직전 응답">{describePreviousFrom(turnMetrics)}</Field>
          </dl>
        )}
        {(turnDetail.mismatches.length > 0 || turnDetail.cautions.length > 0) && (
          <ul className="mt-2 space-y-1 text-data">
            {turnDetail.mismatches.map((mismatch, index) => (
              // 서버 순서 그대로이고 바뀌지 않는다.
              <li key={`m${index}`}>
                <span className="text-warn">불일치 · {MISMATCH_LABELS[mismatch.kind]}</span>{" "}
                <span className="text-ink-secondary">{mismatch.detail}</span>
              </li>
            ))}
            {turnDetail.cautions.map((caution, index) => (
              // 서버 순서 그대로이고 바뀌지 않는다.
              <li key={`c${index}`}>
                <span className="text-warn">주의 · {CAUTION_LABELS[caution.kind]}</span>{" "}
                <span className="text-ink-secondary">{caution.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="런 요약">
        <SectionTitle>런 요약</SectionTitle>
        {metrics === undefined ? (
          <MetricsPending isFailed={metricsState.status === "failed"} onRetry={onRetryMetrics} />
        ) : (
          <dl className="mt-1 grid grid-cols-fields gap-x-3 gap-y-1 text-data tabular-nums">
            <Field label="표본">{formatCount(metrics.scored)}턴 (응답 있는 턴)</Field>
            <Field label="응답 없는 턴">{formatCount(metrics.lost)}</Field>
            <Field label="길이 중앙값">{metrics.medianLength === null ? <Missing /> : `${formatCount(metrics.medianLength)}자`}</Field>
            <Field label="문장 중앙값">{metrics.medianSentences === null ? <Missing /> : formatCount(metrics.medianSentences)}</Field>
            <Field label="길이 계속 줄어듦">
              {metrics.lengthNonIncreasing === null ? <Missing /> : yesNo(metrics.lengthNonIncreasing)}
            </Field>
            {RUN_FLAG_ROWS.map(({ key, label }) => (
              <RunFlagField
                key={key}
                label={label}
                count={RUN_FLAG_COUNTS[key](metrics)}
                scored={metrics.scored}
                turns={flaggedTurns(metrics.turns, key)}
                isDanger={key === "broken"}
                knownTurns={knownTurns}
                onSelectTurn={onSelectTurn}
              />
            ))}
          </dl>
        )}
      </section>

      {detail.mismatches.length > 0 && (
        <section aria-label="불일치 턴">
          <SectionTitle count={detail.mismatches.length}>불일치</SectionTitle>
          <TurnLinks
            turns={detail.mismatches.map((mismatch) => mismatch.turn)}
            knownTurns={knownTurns}
            onSelectTurn={onSelectTurn}
            tone="warn"
          />
        </section>
      )}
    </div>
  );
}

type TurnLinksProps = {
  turns: ReadonlyArray<number | null | undefined>;
  knownTurns: ReadonlySet<number>;
  onSelectTurn: (turn: number) => void;
  /** 불일치는 호박(`warn`), 응답 플래그는 보조 글자색(`quiet`) — 플래그는 기록이 어긋난 것이 아니다. */
  tone: "warn" | "quiet";
};

/**
 * 불일치·플래그가 가리키는 턴들. 이 런에 없는 번호(건너뛴 번호·짝 없는 줄의 번호)는 고를 턴이 없어 버튼이 아니라 글자로 적는다.
 */
function TurnLinks({ turns, knownTurns, onSelectTurn, tone }: TurnLinksProps) {
  const unique = [...new Set(turns.filter((turn): turn is number => typeof turn === "number"))].sort((a, b) => a - b);
  if (unique.length === 0) return <Absent>턴을 가리키지 않는 불일치뿐이다 — 아래 상태 줄 목록에서 본다</Absent>;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {unique.map((turn) =>
        knownTurns.has(turn) ? (
          <button
            key={turn}
            type="button"
            onClick={() => onSelectTurn(turn)}
            className={cn(
              "h-6 rounded-sm bg-surface-raised px-1.5 text-label tabular-nums hover:text-ink focus-visible:outline-2 focus-visible:outline-accent",
              tone === "warn" ? "text-warn" : "text-ink-secondary",
            )}
          >
            턴 {turn}
          </button>
        ) : (
          <span key={turn} className="inline-flex h-6 items-center px-1.5 text-label text-ink-muted tabular-nums">
            턴 {turn} · 런에 없음
          </span>
        ),
      )}
    </div>
  );
}

/** 런 지표를 아직 받지 못한 런 요약 자리 — 받는 중이거나, 받지 못했으면 다시 받기. */
function MetricsPending({ isFailed, onRetry }: { isFailed: boolean; onRetry: () => void }) {
  if (!isFailed) return <Absent>런 지표를 받는 중이다</Absent>;
  return (
    <p className="mt-1 text-data text-ink-muted">
      런 지표를 받지 못했다.{" "}
      <button
        type="button"
        onClick={onRetry}
        className="rounded-sm text-ink-secondary underline underline-offset-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      >
        다시 받기
      </button>
    </p>
  );
}

type RunFlagFieldProps = {
  label: string;
  count: number;
  scored: number;
  /** 그 플래그가 선 턴 — 수 아래 접힌 목록에서 그 턴으로 간다. */
  turns: ReadonlyArray<number>;
  isDanger: boolean;
  knownTurns: ReadonlySet<number>;
  onSelectTurn: (turn: number) => void;
};

function RunFlagField({ label, count, scored, turns, isDanger, knownTurns, onSelectTurn }: RunFlagFieldProps) {
  return (
    <Field label={label}>
      <span className={countTone(count, isDanger)}>{formatCount(count)}</span>
      <span className="text-ink-muted"> / 표본 {formatCount(scored)}턴</span>
      {turns.length > 0 && (
        // 플래그가 자주 서는 런(질문·청유 등)에서 턴 버튼이 늘어서지 않게 기본은 접는다.
        <details className="mt-0.5">
          <summary className="cursor-pointer text-label text-ink-secondary hover:text-ink">어느 턴</summary>
          <TurnLinks turns={turns} knownTurns={knownTurns} onSelectTurn={onSelectTurn} tone="quiet" />
        </details>
      )}
    </Field>
  );
}

function GroupTitle({ count, note, children }: { count: number; note?: string; children: ReactNode }) {
  return (
    <h3 className="flex items-baseline gap-1.5 px-3 pt-3 pb-1 text-label font-semibold text-ink-secondary">
      {children}
      <span className="font-normal text-ink-muted tabular-nums">
        {formatCount(count)}
        {note !== undefined && ` · ${note}`}
      </span>
    </h3>
  );
}

function SectionTitle({ count, children }: { count?: number; children: ReactNode }) {
  return (
    <h3 className="flex items-baseline gap-1.5 text-section text-ink">
      {children}
      {count !== undefined && <span className="text-label font-normal text-ink-muted tabular-nums">{formatCount(count)}</span>}
    </h3>
  );
}

/** 측정 서버가 준 기록 한계 문장 하나 — 바꾸지 않고 그대로 싣는다. 값이 있어야 할 자리에 둔다. */
function RecordLimitNote({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <p className={cn("flex items-start gap-2 rounded-md bg-surface-raised px-2 py-1.5 text-data text-ink-secondary", className)}>
      <span aria-hidden="true" className="font-semibold text-ink-muted">
        i
      </span>
      <span>{children}</span>
    </p>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-ink tabular-nums">{children}</dd>
    </>
  );
}

function Absent({ children }: { children: ReactNode }) {
  return <p className="mt-1 text-data text-ink-muted">{children}</p>;
}

/** 값이 있어야 할 자리에 기록이 없다는 것을 말한다 — 대시로 덮지 않는다. */
function Missing() {
  return <span className="text-ink-muted">기록 없음</span>;
}

/**
 * 턴 기록 행에서 읽는 칸(회상·사실)이 왜 비었는가 — 런 전체가 비거나(이전 형식, 파일 없음), 이 시도에 붙은 행이 없다. 행이
 * 있으면 undefined.
 */
function rowAbsence(gap: RecordGap | undefined, rowCount: number): string | undefined {
  if (gap !== undefined) return RECORD_GAP_TEXT[gap];
  return rowCount === 0 ? "이 시도에 붙은 턴 기록 행 없음" : undefined;
}

function RowListState({
  absence,
  count,
  emptyText,
  children,
}: {
  absence: string | undefined;
  count: number;
  emptyText: string;
  children: ReactNode;
}) {
  if (absence !== undefined) return <Absent>{absence}</Absent>;
  if (count === 0) return <Absent>{emptyText}</Absent>;
  return children;
}

function yesNo(value: boolean): string {
  return value ? "예" : "아니오";
}

function countTone(count: number, isDanger: boolean): string {
  if (count === 0) return "text-ink-muted";
  return isDanger ? "text-danger" : "text-ink";
}

function formatScore(score: number | undefined): ReactNode {
  return score === undefined ? <Missing /> : score.toFixed(2);
}

function formatOptionalCount(value: number | undefined): ReactNode {
  return value === undefined ? <Missing /> : `${formatCount(value)}자`;
}
