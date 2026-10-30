import { useMutation, useQueryClient } from "@tanstack/react-query";

import { getRuns } from "@/shared/api/client";

import { runKeys } from "./runKeys";

/**
 * 측정 서버가 런 루트를 다시 훑게 한다(실데이터에서 수십 초). 응답이 곧 새 목록이라 캐시를 무효로 만들어 한 번 더 부르지 않고
 * 받은 목록을 그대로 넣는다. 로컬 서버라 브라우저의 오프라인 판단과 상관없이 보낸다(`useRuns` 와 같은 까닭).
 */
export function useRefreshRuns() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => getRuns({ refresh: true }),
    networkMode: "always",
    onSuccess: (runs) => {
      queryClient.setQueryData(runKeys.list(), runs);
    },
  });
}
