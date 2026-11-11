import { useQuery } from "@tanstack/react-query";

import { hostedRunsQuery, splitHostedRuns, type HostedRunsSplit } from "@/shared/api/service/hostedRuns";
import type { HostedRunList } from "@/shared/api/service/serviceClient";

/**
 * 호스팅 서비스의 런 목록을 표에 갈 런·런별 판·읽지 못하는 런으로 나눠 받는다. 나누기는 모듈 함수로 둔다 — 렌더마다 새 함수를
 * 넘기면 목록이 그대로여도 매번 다시 나눠, 작업대의 트리·행 계산이 매번 다시 돈다.
 */
export function useHostedRuns() {
  return useQuery({ ...hostedRunsQuery(), select: selectSplit });
}

function selectSplit(list: HostedRunList): HostedRunsSplit {
  return splitHostedRuns(list.items);
}
