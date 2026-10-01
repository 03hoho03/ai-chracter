import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { CommentReportList } from "./commentReport";
import { reportKeys, type ReportStatusFilter } from "./keys";

export function useCommentReportListQuery(params: { page: number; status?: ReportStatusFilter }) {
  return useQuery<CommentReportList, ApiError>({
    queryKey: reportKeys.commentList(params),
    queryFn: async () => (await apiClient.get<CommentReportList>("/admin/comment-reports", { params })).data,
  });
}
