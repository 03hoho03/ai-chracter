import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { dashboardKeys } from "./keys";
import type { AdminDashboardCohort } from "./useGrowthQuery";

/** GET /admin/dashboard/cohort-retention — 주별 유지율만 담는 전용 엔드포인트다. `beta=true`면
 * 베타 참가자만, 가입 주가 아니라 **베타 지정 주**로 묶는다. `/growth` 응답에도 같은 표(전체 모드)가
 * 있지만 그 응답의 다른 필드는 베타로 거르지 않으므로, 토글이 한 응답 안에서 필드마다 다른 기준을
 * 섞지 않게 표는 두 모드 모두 이 엔드포인트를 쓴다. */
export function useCohortRetentionQuery(beta: boolean) {
  return useQuery<AdminDashboardCohort[], ApiError>({
    queryKey: dashboardKeys.cohortRetention(beta),
    queryFn: async () =>
      (await apiClient.get<AdminDashboardCohort[]>("/admin/dashboard/cohort-retention", { params: { beta } })).data,
  });
}
