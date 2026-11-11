import { useNavigate, useSearch } from "@tanstack/react-router";

import { isServerUnreachable } from "@/shared/api/isServerUnreachable";
import { readLabError } from "@/shared/api/readLabError";
import { formatCount } from "@/shared/lib/formatNumber";
import { useElapsedSeconds } from "@/shared/lib/useElapsedSeconds";
import { Button } from "@/shared/ui/Button";
import { KeyHint } from "@/shared/ui/KeyHint";
import { AppShell } from "@/widgets/app-shell";

import { useRefreshRuns } from "../api/useRefreshRuns";
import { useRuns } from "../api/useRuns";
import { formatClock } from "../model/runFormat";
import { folderCrumbs } from "./folderCrumbs";
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
          <KeyHint keys={["j", "k"]}>다음·이전 행</KeyHint>
          <KeyHint keys={["Enter"]}>열기</KeyHint>
          <span className="ml-auto truncate">원가 ≥ 는 빠진 호출이 있는 하한 · 내보내기 필요는 턴 기록 파일 없음 · 이전 형식은 턴 기록을 잇지 않음</span>
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
    if (query.isPending || query.isFetching) {
      return (
        <RunListLoading
          seconds={loadingSeconds}
          message="런 목록을 불러오는 중이다. 처음 부르면 측정 서버가 런 루트를 훑어 수십 초 걸린다."
        />
      );
    }
    return <RunListFailure error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.data.items.length === 0) {
    return <RunListEmpty refreshLabel={refreshLabel} isRefreshing={isRefreshing} onRefresh={onRefresh} />;
  }
  return <RunWorkbench items={query.data.items} folder={folder} selectedRowKey={selectedRowKey} />;
}

function failureDetail(error: unknown): string {
  if (isServerUnreachable(error)) return "측정 서버에 연결하지 못했다";
  return readLabError(error)?.detail ?? (error instanceof Error ? error.message : "");
}
