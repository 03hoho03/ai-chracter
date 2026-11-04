import { useQuery } from "@tanstack/react-query";

import { getRun } from "@/shared/api/client";
import { runKeys } from "@/shared/api/runKeys";

/**
 * 런 상세(턴 요약·상태 계열·표지·원가·불일치·주의). 측정 서버는 같은 컴퓨터의 로컬 프로세스라 목록과 같이 다시 시도하지 않고
 * (실패는 대개 꺼져 있음이거나 거부라 기다려도 같다), 브라우저가 오프라인이라고 여겨도 요청한다(127.0.0.1 은 닿는다).
 */
export function useRunDetail(runId: string) {
  return useQuery({
    queryKey: runKeys.detail(runId),
    queryFn: () => getRun(runId),
    retry: false,
    networkMode: "always",
  });
}
