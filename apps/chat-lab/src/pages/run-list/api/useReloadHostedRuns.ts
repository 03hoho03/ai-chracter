import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { reloadHostedRuns } from "@/shared/api/service/hostedRuns";

/** "다시 받기" — 옛 판의 캐시를 버리고 보고 있는 목록을 새로 받는다. 받는 동안은 목록 쿼리의 받는 중 상태로 보인다. */
export function useReloadHostedRuns(): () => Promise<void> {
  const queryClient = useQueryClient();
  return useCallback(() => reloadHostedRuns(queryClient), [queryClient]);
}
