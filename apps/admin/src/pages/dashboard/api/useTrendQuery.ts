import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { dashboardKeys } from "./keys";

export type AdminDashboardTrendPoint = components["schemas"]["AdminDashboardTrendPoint"];

/** 최근 30일 일별 신규가입·신규작품·메시지 추이. 데이터 없는 날은 API가 0으로 채워서 준다. */
export function useTrendQuery(days = 30) {
  return useQuery<AdminDashboardTrendPoint[], ApiError>({
    queryKey: dashboardKeys.trend(days),
    queryFn: async () =>
      (
        await apiClient.get<AdminDashboardTrendPoint[]>("/admin/dashboard/trend", {
          params: { days },
        })
      ).data,
  });
}
