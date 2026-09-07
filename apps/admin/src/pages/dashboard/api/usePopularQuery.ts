import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { dashboardKeys } from "./keys";

export type AdminDashboardPopularItem = components["schemas"]["AdminDashboardPopularItem"];

/** `chat_count` 내림차순 Top N — API가 이미 정렬해서 준다. */
export function usePopularQuery(limit = 10) {
  return useQuery<AdminDashboardPopularItem[], ApiError>({
    queryKey: dashboardKeys.popular(limit),
    queryFn: async () =>
      (
        await apiClient.get<AdminDashboardPopularItem[]>("/admin/dashboard/popular", {
          params: { limit },
        })
      ).data,
  });
}
