import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { reportKeys } from "./keys";
import { redactExpiredNovelEvidence, type NovelReportAction, type NovelReportDetail } from "./novelReport";

type NovelReportActionMutationOptions = {
  /** 신고 밖 화면(노벨 상세 등)의 캐시를 무효화할 자리 — 다른 entity 키라 feature 가 넘긴다. */
  onSuccess?: () => Promise<unknown> | void;
};

/** `restrict` 는 그 노벨을 이용제한하고 처리완료로, `reject` 는 반려로. 노벨이 지워졌으면 이용제한은 409 `NOVEL_GONE`. */
export function useNovelReportActionMutation(reportId: string, options: NovelReportActionMutationOptions = {}) {
  const queryClient = useQueryClient();
  return useMutation<NovelReportDetail, ApiError, NovelReportAction>({
    mutationFn: async (payload) =>
      redactExpiredNovelEvidence(
        (await apiClient.post<NovelReportDetail>(`/admin/novel-reports/${reportId}/actions`, payload)).data,
      ),
    onSuccess: async (report) => {
      queryClient.setQueryData(reportKeys.novelDetail(reportId), report);
      await Promise.all([queryClient.invalidateQueries({ queryKey: reportKeys.all }), options.onSuccess?.()]);
    },
  });
}
