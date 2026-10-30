import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getTurn } from "@/shared/api/client";
import { runKeys } from "@/shared/api/runKeys";

/**
 * 고른 턴의 상세(시도·덤프·턴 기록·기억 스냅숏·기록 한계). 턴을 옮기는 동안 앞 턴 내용을 그대로 두어(`placeholderData`) 화면이
 * 빈 칸으로 깜빡이지 않게 하고, 화면은 `isPlaceholderData` 로 그 내용을 흐리게 그린다. 재시도·네트워크 판단은 런 상세와 같다.
 */
export function useTurnDetail(runId: string, turn: number | undefined) {
  return useQuery({
    queryKey: runKeys.turn(runId, turn ?? 0),
    queryFn: () => getTurn(runId, turn ?? 0),
    enabled: turn !== undefined,
    placeholderData: keepPreviousData,
    retry: false,
    networkMode: "always",
  });
}
