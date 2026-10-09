import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys, type ReportStatusFilter } from "./keys";
import type { NovelCommentReportList } from "./novelReport";

export function useNovelCommentReportListQuery(params: { page: number; status?: ReportStatusFilter }) {
  return useQuery<NovelCommentReportList, ApiError>({
    queryKey: reportKeys.novelCommentList(params),
    queryFn: async () => (await apiClient.get<NovelCommentReportList>("/admin/novel-comment-reports", { params })).data,
  });
}
