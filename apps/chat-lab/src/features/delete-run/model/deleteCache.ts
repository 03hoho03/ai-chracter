import type { QueryClient } from "@tanstack/react-query";

import { runKeys } from "@/shared/api/runKeys";
import { describeHostedFailure } from "@/shared/api/service/hostedFailure";
import { hostedRunKeys } from "@/shared/api/service/hostedRuns";
import type { HostedRunList } from "@/shared/api/service/serviceClient";

/**
 * 지운 런의 캐시를 버린다(낡은 것이 아니라 없어진 것이라 무효화가 아니라 제거다). 목록은 그 런만 빼고 다시 받지 않는다 — 다시 받아
 * 다른 런의 최신 판이 바뀌면, 이미 열어 둔 옛 판과 새로 고른 턴의 새 판이 한 화면에 섞인다. 다시 받지 않았으니 받은 때도 그대로
 * 둔다(목록 머리의 "받은 때"가 지운 시각이 되면 나머지 런을 그때 받은 것처럼 읽힌다).
 */
export function clearDeletedRunCache(queryClient: QueryClient, runId: string): void {
  const receivedAt = queryClient.getQueryState(hostedRunKeys.list())?.dataUpdatedAt;
  queryClient.setQueryData<HostedRunList>(
    hostedRunKeys.list(),
    (list) => (list === undefined ? undefined : { ...list, items: list.items.filter((item) => item.runId !== runId) }),
    { updatedAt: receivedAt },
  );
  queryClient.removeQueries({ queryKey: hostedRunKeys.bundlesOf(runId) });
  queryClient.removeQueries({ queryKey: runKeys.run(runId) });
}

/**
 * 지우기가 404 로 끝났으면(누가 먼저 지웠다) 지운 것과 같은 정리를 하고 참. 그 밖의 실패는 캐시를 건드리지 않는다 — 대화에 실패를
 * 보이고 다시 누를 수 있다.
 */
export function clearIfAlreadyDeleted(queryClient: QueryClient, runId: string, error: unknown): boolean {
  if (describeHostedFailure(error, "delete").kind !== "notFound") return false;
  clearDeletedRunCache(queryClient, runId);
  return true;
}

/**
 * 지우기 직전에 새로 받은 목록에서 그 런이 대화를 연 때와 달랐을 때 — 목록 캐시의 그 런 줄만 새 값으로 바꿔 대화가 새 판 수로 다시
 * 그려지게 한다. 다른 런의 줄은 그대로 둔다 — 목록 전체를 바꾸면 다른 런의 최신 판이 바뀌어 열어 둔 옛 판과 섞이고, 새로 올라온 런이
 * 표의 행 순서를 밀어 미리보기(와 그 안의 대화)가 다른 런으로 넘어간다. 다시 받은 것이 그 런 하나라 받은 때도 그대로 둔다.
 */
export function refreshRunEntry(queryClient: QueryClient, fresh: HostedRunList["items"][number]): void {
  const listKey = hostedRunKeys.list();
  const seen = queryClient.getQueryData<HostedRunList>(listKey)?.items.find((item) => item.runId === fresh.runId);
  queryClient.setQueryData<HostedRunList>(
    listKey,
    (list) =>
      list === undefined
        ? undefined
        : { ...list, items: list.items.map((item) => (item.runId === fresh.runId ? fresh : item)) },
    { updatedAt: queryClient.getQueryState(listKey)?.dataUpdatedAt },
  );
  if (seen?.latest.sha256 === fresh.latest.sha256) return;
  // 최신 판이 바뀌었으면 옛 판에서 나온 캐시는 틀렸다. 보고 있지 않은 것은 버린다.
  queryClient.removeQueries({ queryKey: hostedRunKeys.bundlesOf(fresh.runId) });
  queryClient.removeQueries({ queryKey: runKeys.run(fresh.runId), type: "inactive" });
  // 상세 머리에서 연 대화면 그 상세가 보고 있다 — 버리지 않고 다시 받아(받는 동안 앞 내용을 둔다) 화면째 새 판으로 옮긴다. 버리면
  // 상세가 로딩으로 바뀌며 대화가 선 머리 자리까지 사라진다.
  void queryClient.refetchQueries({ queryKey: runKeys.run(fresh.runId), type: "active" });
}
