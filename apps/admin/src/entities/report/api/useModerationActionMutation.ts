import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys } from "./keys";
import type { AdminReportDetailResponse } from "./useReportDetailQuery";

export type ModerationActionType = components["schemas"]["ModerationActionType"];

type ModerationActionPayload = {
  action: ModerationActionType;
  adminComment?: string;
  /** 이용제한·삭제가 신고된 작품으로 만든 노벨을 어떻게 할지. 빼면 서버는 닫고 환급한다(정책 스위치가 꺼져 있으면 환급도 없다). */
  derivativeNovels?: components["schemas"]["ReportActionRequest"]["derivativeNovels"];
};

/** 조치 확정 후 신고 목록/상세 쿼리를 모두 무효화한다. */
export function useModerationActionMutation(reportId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminReportDetailResponse, ApiError, ModerationActionPayload>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminReportDetailResponse>(`/admin/reports/${reportId}/action`, payload)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reportKeys.all }),
  });
}
