import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { reportKeys, type ReportStatusFilter } from "./keys";

export type AdminReportListResponse = components["schemas"]["AdminReportListResponse"];

/** techspec-admin.md §1 — 전통적(offset) 페이지네이션. `status` 미지정 시 전체 조회. */
export function useReportListQuery(params: { page: number; status?: ReportStatusFilter }) {
  return useQuery<AdminReportListResponse, ApiError>({
    queryKey: reportKeys.list(params),
    queryFn: async () =>
      (
        await apiClient.get<AdminReportListResponse>("/admin/reports", {
          params: { page: params.page, status: params.status },
        })
      ).data,
  });
}
