import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";
import { dashboardKeys } from "./keys";

export type AdminDashboardActivityResponse = components["schemas"]["AdminDashboardActivityResponse"];

export function useActivityQuery() {
  return useQuery<AdminDashboardActivityResponse, ApiError>({
    queryKey: dashboardKeys.activity(),
    queryFn: async () =>
      (await apiClient.get<AdminDashboardActivityResponse>("/admin/dashboard/activity")).data,
  });
}
