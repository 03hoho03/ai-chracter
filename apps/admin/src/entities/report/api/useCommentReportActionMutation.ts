import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { CommentReportAction, CommentReportDetail } from "./commentReport";
import { reportKeys } from "./keys";
import { redactExpiredEvidence } from "./redactExpiredEvidence";

type CommentReportActionMutationOptions = {
  onSuccess?: (report: CommentReportDetail) => Promise<void> | void;
};

export function useCommentReportActionMutation(reportId: string, options: CommentReportActionMutationOptions = {}) {
  const queryClient = useQueryClient();
  return useMutation<CommentReportDetail, ApiError, CommentReportAction>({
    networkMode: "always",
    mutationFn: async (payload) => redactExpiredEvidence(
      (await apiClient.post<CommentReportDetail>(`/admin/comment-reports/${reportId}/actions`, payload)).data,
    ),
    onSuccess: async (report) => {
      queryClient.setQueryData(reportKeys.commentDetail(reportId), report);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: reportKeys.all }),
        options.onSuccess?.(report),
      ]);
    },
  });
}
