import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { reportKeys } from "./keys";
import type { AdminReportDetailResponse } from "./useReportDetailQuery";

export type ModerationActionType = components["schemas"]["ModerationActionType"];

type ModerationActionPayload = {
  action: ModerationActionType;
  adminComment?: string;
};

/** techspec-admin.md §1 — 조치 확정 후 신고 목록/상세 쿼리를 모두 무효화한다(US-122 AC5). */
export function useModerationActionMutation(reportId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminReportDetailResponse, ApiError, ModerationActionPayload>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminReportDetailResponse>(`/admin/reports/${reportId}/action`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reportKeys.all }),
  });
}
