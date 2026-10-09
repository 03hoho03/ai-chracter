import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys, type ReportStatusFilter } from "./keys";
import type { NovelReportList } from "./novelReport";

export function useNovelReportListQuery(params: { page: number; status?: ReportStatusFilter }) {
  return useQuery<NovelReportList, ApiError>({
    queryKey: reportKeys.novelList(params),
    queryFn: async () => (await apiClient.get<NovelReportList>("/admin/novel-reports", { params })).data,
  });
}
