import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { reportKeys } from "./keys";

export type AdminReportDetailResponse = components["schemas"]["AdminReportDetailResponse"];

export function useReportDetailQuery(reportId: string) {
  return useQuery<AdminReportDetailResponse, ApiError>({
    queryKey: reportKeys.detail(reportId),
    queryFn: async () => (await apiClient.get<AdminReportDetailResponse>(`/admin/reports/${reportId}`)).data,
  });
}
