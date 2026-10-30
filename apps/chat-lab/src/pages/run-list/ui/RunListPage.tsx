import { useNavigate, useSearch } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { cn } from "@/shared/lib/cn";
import { Button } from "@/shared/ui/Button";
import { Kbd } from "@/shared/ui/Kbd";
import { AppShell, type Crumb } from "@/widgets/app-shell";

import { useRefreshRuns } from "../api/useRefreshRuns";
import { useRuns } from "../api/useRuns";
import { useElapsedSeconds } from "../lib/useElapsedSeconds";
import { formatClock, formatCount } from "../model/runFormat";
import { RunListEmpty } from "./RunListEmpty";
import { RunListFailure } from "./RunListFailure";
import { RunListLoading } from "./RunListLoading";
import { RunWorkbench } from "./RunWorkbench";

/** 런 목록(세션 층). 측정 서버가 찾은 런을 폴더 트리·표·미리보기 3열로 보인다. */
export function RunListPage() {
  const search = useSearch({ from: "/" });
  const navigate = useNavigate({ from: "/" });
  const runsQuery = useRuns();
  const refresh = useRefreshRuns();
  const loadingSeconds = useElapsedSeconds(runsQuery.isFetching && runsQuery.data === undefined);
  const refreshSeconds = useElapsedSeconds(refresh.isPending);
  const folder = search.folder ?? "";
  const runs = runsQuery.data;
  const refreshLabel = refresh.isPending ? `훑는 중 ${refreshSeconds}초` : "새로 훑기";

  function handleSelectFolder(path: string) {
    void navigate({ search: path === "" ? {} : { folder: path } });
  }

  function handleRefresh() {
    refresh.mutate();
  }

  return (
    <AppShell
      crumbs={folderCrumbs(folder, handleSelectFolder)}
      meta={runs ? `런 ${formatCount(runs.items.length)}개 · 탐색 ${formatClock(runs.discoveredAt)}` : undefined}
      actions={
        <>
          {refresh.isError && (
            <span role="alert" title={failureDetail(refresh.error)} className="truncate text-data text-danger">
              새로 훑지 못했다
            </span>
          )}
          {runs !== undefined && runs.items.length > 0 && (
            <Button onClick={handleRefresh} disabled={refresh.isPending} className="tabular-nums">
              {refreshLabel}
            </Button>
          )}
        </>
      }
      hints={
        <>
          <Hint keys={["j", "k"]}>다음·이전 행</Hint>
          <Hint keys={["Enter"]}>열기</Hint>
          <span className="ml-auto truncate">원가 ≥ 는 빠진 호출이 있는 하한 · 내보내기 필요는 턴 기록 파일 없음</span>
        </>
      }
    >
      <RunListBody
        query={runsQuery}
        loadingSeconds={loadingSeconds}
        folder={folder}
        selectedRowKey={search.row}
        refreshLabel={refreshLabel}
        isRefreshing={refresh.isPending}
        onRefresh={handleRefresh}
      />
    </AppShell>
  );
}

type RunListBodyProps = {
  query: ReturnType<typeof useRuns>;
  loadingSeconds: number;
  folder: string;
  selectedRowKey: string | undefined;
  refreshLabel: string;
  isRefreshing: boolean;
  onRefresh: () => void;
};

/**
 * 본문의 갈래. 한 번 받은 목록은 뒤이은 다시 받기가 실패해도 그대로 보인다 — 화면을 실패 안내로 갈아엎으면 보던 자리를 잃는다.
 * 목록이 없는 채로 다시 받는 중이면(실패 뒤 "다시 시도") 실패 안내 대신 로딩을 보인다 — 서버를 띄운 뒤 누른 다시 시도가 첫
 * 훑기로 수십 초 걸리는 동안 옛 실패 문구가 남아 있으면 눌림이 먹지 않은 것처럼 보인다.
 */
function RunListBody({ query, loadingSeconds, folder, selectedRowKey, refreshLabel, isRefreshing, onRefresh }: RunListBodyProps) {
  if (query.data === undefined) {
    if (query.isPending || query.isFetching) return <RunListLoading seconds={loadingSeconds} />;
    return <RunListFailure error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.data.items.length === 0) {
    return <RunListEmpty refreshLabel={refreshLabel} isRefreshing={isRefreshing} onRefresh={onRefresh} />;
  }
  return <RunWorkbench items={query.data.items} folder={folder} selectedRowKey={selectedRowKey} />;
}

/** 헤더 빵부스러기 — `런` 다음에 고른 폴더의 마디마다 한 칸. 누르면 그 폴더로 간다. */
function folderCrumbs(folder: string, onSelect: (path: string) => void): Crumb[] {
  const names = folder === "" ? [] : folder.split("/");
  return [
    {
      key: "",
      content: (
        <CrumbButton isCurrent={names.length === 0} onClick={() => onSelect("")}>
          런
        </CrumbButton>
      ),
    },
    ...names.map((name, index) => {
      const path = names.slice(0, index + 1).join("/");
      return {
        key: path,
        content: (
          <CrumbButton isMono isCurrent={index === names.length - 1} onClick={() => onSelect(path)}>
            {name}
          </CrumbButton>
        ),
      };
    }),
  ];
}

type CrumbButtonProps = {
  isCurrent: boolean;
  isMono?: boolean;
  onClick: () => void;
  children: ReactNode;
};

function CrumbButton({ isCurrent, isMono = false, onClick, children }: CrumbButtonProps) {
  return (
    <button
      type="button"
      aria-current={isCurrent ? "location" : undefined}
      onClick={onClick}
      className={cn(
        "max-w-full truncate rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        isMono ? "font-mono text-data" : "text-body",
        isCurrent ? "font-semibold text-ink" : "text-ink-secondary hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function Hint({ keys, children }: { keys: ReadonlyArray<string>; children: ReactNode }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1">
      {keys.map((key) => (
        <Kbd key={key}>{key}</Kbd>
      ))}
      <span className="ml-0.5">{children}</span>
    </span>
  );
}

function failureDetail(error: unknown): string {
  if (isServerUnreachable(error)) return "측정 서버에 연결하지 못했다";
  return readLabError(error)?.detail ?? (error instanceof Error ? error.message : "");
}
