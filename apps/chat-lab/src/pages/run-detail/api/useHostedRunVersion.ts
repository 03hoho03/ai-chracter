import { useQuery } from "@tanstack/react-query";

import { hostedRunsQuery, type HostedRunVersion } from "@/shared/api/service/hostedRuns";

/**
 * 이 런의 최신 판과 살아 있는 판 수 — 상세 머리의 원문 표지·판·지우기가 읽는다. 상세를 읽은 묶음 로더가 같은 목록 캐시를 채우므로
 * 따로 받지 않는다(캐시가 비어 있으면 로더와 같은 요청 하나로 합쳐진다).
 */
export function useHostedRunVersion(runId: string): HostedRunVersion | undefined {
  const { data } = useQuery({
    ...hostedRunsQuery(),
    select: (list) => {
      const item = list.items.find((candidate) => candidate.runId === runId);
      return item === undefined ? undefined : { latest: item.latest, versionCount: item.versionCount };
    },
  });
  return data;
}
