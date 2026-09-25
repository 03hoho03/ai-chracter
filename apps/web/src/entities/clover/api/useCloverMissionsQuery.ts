import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { cloverKeys } from "./keys";

export type CloverMissionItem = components["schemas"]["CloverMissionItem"];
export type CloverMissionsResponse = components["schemas"]["CloverMissionsResponse"];

/** `achieved`·`claimed`는 BE가 매 조회마다 EXISTS로 다시
 * 계산해 돌려준다(저장된 상태가 아니다). 그래서 이 쿼리도 `staleTime` 없이 기본값을 쓴다 —
 * 캐시된 값을 오래 믿을 이유가 없다(잔액 쿼리의 30초 유한 staleTime과 다른 이유). */
export function useCloverMissionsQuery() {
  return useQuery({
    queryKey: cloverKeys.missions(),
    queryFn: async () =>
      (await apiClient.get<CloverMissionsResponse>("/me/clover/missions")).data,
  });
}
