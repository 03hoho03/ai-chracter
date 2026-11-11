import { useNavigate, useSearch } from "@tanstack/react-router";

import { useLastDeletion, type DeleteOutcome } from "@/features/delete-run";
import { describeHostedFailure } from "@/shared/api/service/hostedFailure";
import { assertNever } from "@/shared/lib/assertNever";
import { formatCount } from "@/shared/lib/formatNumber";
import { useElapsedSeconds } from "@/shared/lib/useElapsedSeconds";
import { Button } from "@/shared/ui/Button";
import { HostedFailureNotice } from "@/shared/ui/HostedFailureNotice";
import { KeyHint } from "@/shared/ui/KeyHint";
import { AppShell } from "@/widgets/app-shell";

import { useHostedRuns } from "../api/useHostedRuns";
import { useReloadHostedRuns } from "../api/useReloadHostedRuns";
import { formatClock } from "../model/runFormat";
import { folderCrumbs } from "./folderCrumbs";
import { HostedRunListEmpty } from "./HostedRunListEmpty";
import { RunListLoading } from "./RunListLoading";
import { RunWorkbench } from "./RunWorkbench";
import { UnreadableRuns } from "./UnreadableRuns";

/**
 * 호스팅 서비스의 런 목록 — 로컬 목록과 같은 3열 작업대에 원문 칩과 미리보기의 판 칸을 더한다. 목록은 처음 받기·다시 받기·지우기로만
 * 바뀐다. 측정 서버가 있어야 하는 "새로 훑기" 자리에 "다시 받기"가 선다.
 */
export function HostedRunListPage() {
  const search = useSearch({ from: "/" });
  const navigate = useNavigate({ from: "/" });
  const runsQuery = useHostedRuns();
  const reload = useReloadHostedRuns();
  const lastDeletion = useLastDeletion();
  const loadingSeconds = useElapsedSeconds(runsQuery.isFetching && runsQuery.data === undefined);
  const folder = search.folder ?? "";
  const split = runsQuery.data;
  const runCount = split === undefined ? 0 : split.runs.length + split.unreadable.length;

  function handleSelectFolder(path: string) {
    void navigate({ search: path === "" ? {} : { folder: path } });
  }

  function handleReload() {
    void reload();
  }

  return (
    <AppShell
      crumbs={folderCrumbs(folder, handleSelectFolder)}
      meta={
        split === undefined
          ? undefined
          : `런 ${formatCount(runCount)}개 · 받은 때 ${formatClock(new Date(runsQuery.dataUpdatedAt).toISOString())}`
      }
      actions={
        <>
          {/* 빈 채로도 늘 두어, 지운 뒤 들어온 문장을 읽기 프로그램이 알린다(나중에 생긴 상태 영역은 알리지 않는 읽기 프로그램이 있다). */}
          <span role="status" className="truncate text-data text-ink-secondary tabular-nums">
            {lastDeletion !== undefined && deletionText(lastDeletion)}
          </span>
          {runCount > 0 && (
            <Button onClick={handleReload} disabled={runsQuery.isFetching}>
              다시 받기
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
      <HostedRunListBody
        query={runsQuery}
        loadingSeconds={loadingSeconds}
        folder={folder}
        selectedRowKey={search.row}
        onReload={handleReload}
      />
    </AppShell>
  );
}

type HostedRunListBodyProps = {
  query: ReturnType<typeof useHostedRuns>;
  loadingSeconds: number;
  folder: string;
  selectedRowKey: string | undefined;
  onReload: () => void;
};

/**
 * 본문의 갈래. 목록이 없는 채로 받는 중이면(처음·다시 받기·실패 뒤 다시 시도) 로딩을 보인다. 읽지 못하는 런만 있어도 작업대를 그려
 * 띠에서 지울 수 있게 한다.
 */
function HostedRunListBody({ query, loadingSeconds, folder, selectedRowKey, onReload }: HostedRunListBodyProps) {
  if (query.data === undefined) {
    if (query.isPending || query.isFetching) {
      return <RunListLoading seconds={loadingSeconds} message="서비스에서 런 목록을 받는 중이다." />;
    }
    return (
      <HostedFailureNotice
        failure={describeHostedFailure(query.error, "list")}
        subject="list"
        onRetry={() => void query.refetch()}
      />
    );
  }
  const { runs, versions, unreadable } = query.data;
  if (runs.length === 0 && unreadable.length === 0) {
    return <HostedRunListEmpty isReloading={query.isFetching} onReload={onReload} />;
  }
  return (
    <RunWorkbench
      items={runs}
      folder={folder}
      selectedRowKey={selectedRowKey}
      versions={versions}
      tableTop={unreadable.length > 0 ? <UnreadableRuns runs={unreadable} /> : undefined}
    />
  );
}

/** 목록 머리의 지운 뒤 문장. 판 수는 서비스가 센 지운 판 수다. */
function deletionText(outcome: DeleteOutcome): string {
  switch (outcome.kind) {
    case "deleted":
      return `지웠다 · 판 ${formatCount(outcome.deletedVersions)}개`;
    case "alreadyDeleted":
      return "이미 지워진 런이다";
    default:
      return assertNever(outcome);
  }
}
