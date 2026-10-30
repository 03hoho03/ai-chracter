import { useQuery } from "@tanstack/react-query";

import { getRunMetrics } from "@/shared/api/client";
import { runKeys } from "@/shared/api/runKeys";

/** 런 지표(턴별 플래그·런 요약). 턴 목록의 플래그 열과 검사기 지표 탭이 쓴다. 재시도·네트워크 판단은 런 상세와 같다. */
export function useRunMetrics(runId: string) {
  return useQuery({
    queryKey: runKeys.metrics(runId),
    queryFn: () => getRunMetrics(runId),
    retry: false,
    networkMode: "always",
  });
}
