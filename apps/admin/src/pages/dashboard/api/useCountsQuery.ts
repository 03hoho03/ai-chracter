import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { dashboardKeys } from "./keys";

export type AdminDashboardCountsResponse = components["schemas"]["AdminDashboardCountsResponse"];

export function useCountsQuery() {
  return useQuery<AdminDashboardCountsResponse, ApiError>({
    queryKey: dashboardKeys.counts(),
    queryFn: async () =>
      (await apiClient.get<AdminDashboardCountsResponse>("/admin/dashboard/counts")).data,
  });
}
