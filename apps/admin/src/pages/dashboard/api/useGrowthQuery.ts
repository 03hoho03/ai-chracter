import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { dashboardKeys } from "./keys";

export type AdminDashboardGrowthResponse = components["schemas"]["AdminDashboardGrowthResponse"];
export type AdminDashboardCohort = components["schemas"]["AdminDashboardCohort"];

export function useGrowthQuery() {
  return useQuery<AdminDashboardGrowthResponse, ApiError>({
    queryKey: dashboardKeys.growth(),
    queryFn: async () =>
      (await apiClient.get<AdminDashboardGrowthResponse>("/admin/dashboard/growth")).data,
  });
}
