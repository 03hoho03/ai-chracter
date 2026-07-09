import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { usageMetricsKeys } from "./keys";

export type UsageMetricsResponse = components["schemas"]["UsageMetricsResponse"];

/** techspec-admin.md §3 — from/to(YYYY-MM-DD) 기간의 사용량 지표(일/월 평균, 추이)를 조회한다. */
export function useUsageMetricsQuery(params: { from: string; to: string }) {
  return useQuery<UsageMetricsResponse, ApiError>({
    queryKey: usageMetricsKeys.range(params),
    queryFn: async () =>
      (
        await apiClient.get<UsageMetricsResponse>("/admin/usage-metrics", {
          params: { from: params.from, to: params.to },
        })
      ).data,
  });
}
