import { Link, useParams } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import type { RunDetail } from "@/shared/api/client";
import { COST_GAP_TEXT, OLD_FORMAT_EXPORT_REASON, runRecordGap } from "@/shared/api/recordGap";
import { staticBundleState, type StaticBundleState } from "@/shared/api/staticBundle";
import { cn } from "@/shared/lib/cn";
import { formatCount, formatUsd } from "@/shared/lib/formatNumber";
import { useElapsedSeconds } from "@/shared/lib/useElapsedSeconds";
import { Button } from "@/shared/ui/Button";
import { KeyHint } from "@/shared/ui/KeyHint";
import { AppShell, type Crumb } from "@/widgets/app-shell";

import { useExportTurns } from "../api/useExportTurns";
import { useRunDetail } from "../api/useRunDetail";
import { describeExportFailure } from "../model/exportFailure";
import { ExportNotice, type ExportFeedback } from "./ExportNotice";
import { RunDetailFailure } from "./RunDetailFailure";
import { RunDetailLoading } from "./RunDetailLoading";
import { RunWorkspace } from "./RunWorkspace";

/**
 * 런 상세(턴 층). 위 상태 타임라인 띠 아래에 턴 목록 │ 대화·원문 │ 호출 검사기 3열. 고른 턴·시도·탭은 주소에 실린다.
 * 헤더의 주 행동은 "턴 기록 내보내기" 하나다 — 턴 기록 파일이 있어야 원가·토큰·숨김 스탯이 채워진다. 정적 HTML 로 연 화면은
 * 측정 서버가 없어 내보낼 수 없으므로, 그 자리에 이 파일이 무엇인지(원문을 담았는지)를 적는다.
 */
export function RunDetailPage() {
  const { runId } = useParams({ from: "/runs/$runId" });
  // 다른 런으로 옮기면(뒤로·앞으로 가기 등) 화면 상태를 새로 시작한다 — 앞 런의 내보내기 알림·펼친 불일치 목록이 새 런에 남지
  // 않고, 턴 상세의 앞 내용(흐리게 남겨 두는 것)·검색어도 비운다. 앞 런에서 아직 끝나지 않은 내보내기의 알림도 새 런에 뜨지 않는다.
  return <RunDetailScreen key={runId} runId={runId} />;
}

function RunDetailScreen({ runId }: { runId: string }) {
  const detailQuery = useRunDetail(runId);
  const exportTurns = useExportTurns(runId);
  const [exportFeedback, setExportFeedback] = useState<ExportFeedback | undefined>(undefined);
  const [isIssuesOpen, setIsIssuesOpen] = useState(false);
  const loadingSeconds = useElapsedSeconds(detailQuery.isFetching && detailQuery.data === undefined);
  const exportSeconds = useElapsedSeconds(exportTurns.isPending);
  const detail = detailQuery.data;
  const staticState = staticBundleState();

  function handleExport(force: boolean) {
    setExportFeedback(undefined);
    exportTurns.mutate(force, {
      onSuccess: (result) => setExportFeedback({ kind: "done", path: result.path }),
      onError: (error) => setExportFeedback({ kind: "failed", failure: describeExportFailure(error) }),
    });
  }

  function handleToggleIssues() {
    setIsIssuesOpen((previous) => !previous);
  }

  return (
    <AppShell
      crumbs={detailCrumbs(runId, detail, staticState.kind !== "absent")}
      meta={detail ? runMeta(detail) : undefined}
      badges={
        detail && (
          <IssueBadges
            mismatchCount={detail.mismatches.length}
            cautionCount={detail.cautions.length}
            isOpen={isIssuesOpen}
            onToggle={handleToggleIssues}
          />
        )
      }
      actions={
        detail && (
          <RunAction
            detail={detail}
            staticState={staticState}
            isExporting={exportTurns.isPending}
            exportSeconds={exportSeconds}
            onExport={() => handleExport(false)}
          />
        )
      }
      hints={
        <>
          {detail && (
            <IssueToggle
              mismatchCount={detail.mismatches.length}
              cautionCount={detail.cautions.length}
              isOpen={isIssuesOpen}
              onToggle={handleToggleIssues}
            />
          )}
          <KeyHint keys={["j", "k"]}>턴</KeyHint>
          <KeyHint keys={["[", "]"]}>시도</KeyHint>
          <KeyHint keys={["/"]}>원문 검색</KeyHint>
          <KeyHint keys={["n", "N"]}>일치</KeyHint>
          <KeyHint keys={["1–4"]}>검사기 탭</KeyHint>
          <KeyHint keys={["g"]}>타임라인</KeyHint>
          <KeyHint keys={["Esc"]}>닫기</KeyHint>
        </>
      }
    >
      <RunDetailBody
        query={detailQuery}
        runId={runId}
        loadingSeconds={loadingSeconds}
        notice={
          exportFeedback && (
            <ExportNotice
              feedback={exportFeedback}
              isPending={exportTurns.isPending}
              onOverwrite={() => handleExport(true)}
              onDismiss={() => setExportFeedback(undefined)}
            />
          )
        }
        isIssuesOpen={isIssuesOpen}
        onCloseIssues={() => setIsIssuesOpen(false)}
      />
    </AppShell>
  );
}

type RunDetailBodyProps = {
  query: ReturnType<typeof useRunDetail>;
  runId: string;
  loadingSeconds: number;
  notice: ReactNode;
  isIssuesOpen: boolean;
  onCloseIssues: () => void;
};

/**
 * 본문의 갈래. 한 번 받은 상세는 뒤이은 다시 받기(내보낸 뒤 무효화 등)가 실패해도 그대로 보인다 — 보던 자리를 잃지 않게. 상세가
 * 없는 채로 다시 받는 중이면(실패 뒤 "다시 시도") 실패 안내 대신 로딩을 보인다.
 */
function RunDetailBody({ query, runId, loadingSeconds, notice, isIssuesOpen, onCloseIssues }: RunDetailBodyProps) {
  if (query.data === undefined) {
    if (query.isPending || query.isFetching) return <RunDetailLoading seconds={loadingSeconds} />;
    return <RunDetailFailure error={query.error} onRetry={() => void query.refetch()} />;
  }
  return (
    <RunWorkspace
      runId={runId}
      detail={query.data}
      notice={notice}
      isIssuesOpen={isIssuesOpen}
      onCloseIssues={onCloseIssues}
    />
  );
}

type RunActionProps = {
  detail: RunDetail;
  staticState: StaticBundleState;
  isExporting: boolean;
  exportSeconds: number;
  onExport: () => void;
};

/** 헤더 오른쪽의 주 행동 자리 — 턴 기록 내보내기, 또는 그것을 할 수 없는 까닭. */
function RunAction({ detail, staticState, isExporting, exportSeconds, onExport }: RunActionProps) {
  if (staticState.kind !== "absent") return <StaticFileLabel state={staticState} />;
  if (runRecordGap(detail.run) === "oldFormat") {
    // 측정 서버가 이 형식의 내보내기를 거부한다 — 누르면 실패할 버튼 대신 못 하는 까닭을 그 자리에 둔다.
    return (
      <span className="text-data text-ink-muted" title={OLD_FORMAT_EXPORT_REASON}>
        내보내기 없음 · 이전 형식
      </span>
    );
  }
  return (
    <Button
      variant="primary"
      onClick={onExport}
      disabled={isExporting}
      title="로컬 DB 에서 이 런 방의 턴 기록을 런 폴더의 chat-turns.jsonl 로 쓴다"
      className="tabular-nums"
    >
      {isExporting ? (
        `내보내는 중 ${exportSeconds}초`
      ) : (
        <>
          <span className="sm:hidden">{detail.run.hasChatTurns ? "다시 내보내기" : "내보내기"}</span>
          <span className="hidden sm:inline">
            {detail.run.hasChatTurns ? "턴 기록 다시 내보내기" : "턴 기록 내보내기"}
          </span>
        </>
      )}
    </Button>
  );
}

const STATIC_FILE_NOTE = {
  withoutRaw: "측정 서버 없이 여는 정적 HTML 이다. 프롬프트·지시문 원문과 기억 노트·요약 본문은 빼고 내보냈다.",
  withRaw: "측정 서버 없이 여는 정적 HTML 이다. 원문까지 담아 내보냈다 — 공개 저장소에 커밋하지 않는다.",
} as const;

/**
 * 정적 HTML 로 연 화면의 표시 — 내보내기 버튼 자리에, 이전 형식 런의 "내보내기 없음"과 같은 조용한 한 줄로. 원문을 담았는지가
 * 이 파일을 남에게 건네도 되는지를 가르므로 함께 적는다. 읽지 못한 파일이면 본문이 까닭을 보인다.
 */
function StaticFileLabel({ state }: { state: Exclude<StaticBundleState, { kind: "absent" }> }) {
  if (state.kind === "broken") return <span className="text-data text-ink-muted">정적 파일</span>;
  const hasRaw = state.bundle.raw;
  return (
    <span className="text-data text-ink-muted" title={hasRaw ? STATIC_FILE_NOTE.withRaw : STATIC_FILE_NOTE.withoutRaw}>
      정적 파일 · {hasRaw ? "원문 포함" : "원문 제외"}
    </span>
  );
}

/**
 * 빵부스러기 — `런`(목록으로, 이 런이 보이는 폴더·행을 골라 둔 채) / 이야기 이름 / 경로. 정적 HTML 에는 목록이 없어 `런` 은 링크가
 * 아닌 글이다.
 */
function detailCrumbs(runId: string, detail: RunDetail | undefined, isStatic: boolean): Crumb[] {
  const crumbs: Crumb[] = [
    {
      key: "runs",
      content: isStatic ? (
        <span className="text-body text-ink-secondary">런</span>
      ) : (
        <Link
          to="/"
          // 대량 시도 폴더 안 런이면 그 폴더를 골라야 표에 런 행이 있다. 밖이면 전체에서 행으로 고른다.
          search={detail?.run.group != null ? { folder: detail.run.group, row: runId } : { row: runId }}
          className="rounded-sm text-body text-ink-secondary hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          런
        </Link>
      ),
    },
  ];
  if (detail === undefined) return crumbs;
  crumbs.push({
    key: "story",
    content: (
      <span className={detail.run.storyName == null ? "text-body text-ink-muted" : "text-body font-semibold text-ink"}>
        {detail.run.storyName ?? "이야기 이름 없음"}
      </span>
    ),
  });
  crumbs.push({
    key: "path",
    content: (
      <span title={detail.run.path} className="hidden font-mono text-data text-ink-muted lg:inline">
        {detail.run.path}
      </span>
    ),
  });
  return crumbs;
}

/**
 * 헤더 보조 정보 — 턴 수와 런 원가. 원가는 `$0.0000` 과 "모름"이 같은 모양이 되지 않게 갈래를 나누고, 측정 서버가 하한으로 본
 * 원가(단가 없는 호출·토큰 없는 호출이 섞임)에는 `≥` 를 붙인다.
 */
function runMeta(detail: RunDetail): string {
  const turns = `턴 ${formatCount(detail.turns.length)}`;
  const { cost } = detail;
  if (cost === null) return `${turns} · 원가 ${COST_GAP_TEXT[runRecordGap(detail.run) ?? "needsExport"]}`;
  const lowerBound = detail.run.costIsLowerBound === true ? "≥ " : "";
  return `${turns} · 원가 ${lowerBound}${formatUsd(cost.totalUsd)}`;
}

type IssueCountsProps = {
  mismatchCount: number;
  cautionCount: number;
  isOpen: boolean;
  onToggle: () => void;
};

/** 헤더의 불일치·주의 배지. 따로 센 두 수이고, 0 이면 그 배지를 그리지 않는다. 누르면 아래 상태 줄의 목록이 펼쳐진다. */
function IssueBadges({ mismatchCount, cautionCount, isOpen, onToggle }: IssueCountsProps) {
  return (
    <>
      {mismatchCount > 0 && (
        <IssueBadgeButton isOpen={isOpen} onToggle={onToggle}>
          불일치 {formatCount(mismatchCount)}
        </IssueBadgeButton>
      )}
      {cautionCount > 0 && (
        <IssueBadgeButton isOpen={isOpen} onToggle={onToggle} isWideOnly>
          주의 {formatCount(cautionCount)}
        </IssueBadgeButton>
      )}
    </>
  );
}

type IssueBadgeButtonProps = {
  isOpen: boolean;
  onToggle: () => void;
  /** 좁은 화면(640px 미만)에서는 숨긴다 — 헤더 한 줄에 배지 둘과 내보내기가 다 들어가지 않는다. */
  isWideOnly?: boolean;
  children: ReactNode;
};

function IssueBadgeButton({ isOpen, onToggle, isWideOnly = false, children }: IssueBadgeButtonProps) {
  return (
    <button
      type="button"
      aria-expanded={isOpen}
      aria-controls="run-issues"
      onClick={onToggle}
      className={cn(
        "h-4.5 items-center rounded-sm bg-surface-raised px-1.5 text-label text-warn tabular-nums",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        isWideOnly ? "hidden sm:inline-flex" : "inline-flex",
      )}
    >
      {children}
    </button>
  );
}

/** 상태 줄 왼쪽 — 불일치·주의 수. 누르면 종류·턴·설명 목록이 상태 줄 위로 펼쳐진다. 둘 다 0 이면 없다고 한 줄. */
function IssueToggle({ mismatchCount, cautionCount, isOpen, onToggle }: IssueCountsProps) {
  if (mismatchCount === 0 && cautionCount === 0) return <span className="shrink-0">불일치·주의 없음</span>;
  return (
    <button
      type="button"
      aria-expanded={isOpen}
      aria-controls="run-issues"
      onClick={onToggle}
      className="inline-flex shrink-0 items-center gap-3 rounded-sm text-warn tabular-nums hover:underline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
    >
      {mismatchCount > 0 && <span>불일치 {formatCount(mismatchCount)}</span>}
      {cautionCount > 0 && <span>주의 {formatCount(cautionCount)}</span>}
      <span aria-hidden="true" className="text-ink-muted">
        {isOpen ? "▾" : "▴"}
      </span>
    </button>
  );
}
